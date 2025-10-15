
import os
import httpx
import json
import locale
import secrets
import io
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import quote
from sqlalchemy import func, cast, Integer

# --- Imports do FastAPI e bibliotecas ---
from fastapi import FastAPI, HTTPException, status, Form, Request, Depends, Response, Header, Path, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
from fpdf import FPDF
from sqlmodel import SQLModel, Session, create_engine, select
from contextlib import asynccontextmanager
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime

# --- IMPORTS DO CLOUDINARY (MOVA ELES PARA CÁ) ---
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- Import dos seus modelos de dados ---
from models import Orcamento, Item, User, Cliente, Contato, ContatoOrcamento

# --- Import do nosso módulo de segurança ---
from security import get_password_hash, verify_password

from pdf_models.modelo_joao import gerar_pdf_joao
from pdf_models.modelo_cacador import gerar_pdf_cacador
from pdf_models.modelo_apresentacao import gerar_pdf_apresentacao
from pdf_models.modelo_construtora_araras import gerar_pdf_construtora_araras
from pdf_models.modelo_relatorio_custo import gerar_pdf_relatorio_custo

PDF_GENERATORS = {
    "joao": gerar_pdf_joao,
    "cacador": gerar_pdf_cacador,
    "apresentacao": gerar_pdf_apresentacao,
    "construtora_araras": gerar_pdf_construtora_araras,
    "default": gerar_pdf_apresentacao 
}

# --- CONFIGURAÇÃO INICIAL E CONSTANTES ---
load_dotenv()

cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    print("Aviso: Localidade 'pt_BR.UTF-8' não encontrada.")

USERNAME = os.getenv("BASIC_AUTH_USER", "admin")
PASSWORD = os.getenv("BASIC_AUTH_PASS", "secret")

BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")

# --- BANCO DE DADOS ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definida no arquivo .env")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,             # Número de conexões para manter no pool
    max_overflow=2,           # Conexões extras permitidas em picos de uso
    pool_recycle=300,         # Essencial: Recicla conexões a cada 5 minutos (300s)
    pool_pre_ping=True        # Essencial: Verifica se a conexão está "viva" antes de usar
)

def create_db_and_tables():
    print("INFO:     Criando/Verificando tabelas no banco de dados PostgreSQL...")
    SQLModel.metadata.create_all(engine)
    print("INFO:     Tabelas prontas.")


def format_brl(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- CLASSE DE GERAÇÃO DE PDF (Sua lógica de desenho vai aqui) ---
# Constantes para o PDF
FULL_PAGE_BACKGROUND_IMAGE = os.path.join(STATIC_DIR, 'full_page_background.png')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo.png')
FIXED_RECT_HEIGHT = 7
PADDING_RECT_VERTICAL = 1
LINE_HEIGHT = 4
TABLE_COL_WIDTHS = [10, 80, 30, 40, 30]
TABLE_TOTAL_WIDTH = sum(TABLE_COL_WIDTHS)

create_db_and_tables()

app = FastAPI(title="Orçamento API")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "uma_chave_muito_secreta"))
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory="templates") 

# --- LÓGICA PARA CRIAR O PRIMEIRO USUÁRIO ---
with Session(engine) as session:
    # Verifica se já existe algum usuário no banco
    user_in_db = session.exec(select(User)).first()
    
    # Se não houver nenhum usuário, cria o usuário padrão
    if not user_in_db:
        # Pega o usuário e senha do .env
        admin_username = os.getenv("BASIC_AUTH_USER", "admin")
        admin_password = os.getenv("BASIC_AUTH_PASS", "secret")
        
        # Criptografa a senha antes de salvar
        hashed_password = get_password_hash(admin_password)
        
        # Cria o objeto User e salva no banco
        admin_user = User(username=admin_username, hashed_password=hashed_password, pdf_template_name="joao" )
        session.add(admin_user)
        session.commit()
        print(f"Usuário '{admin_username}' criado com sucesso com a senha padrão.")

FECHAMENTO_USERS = [u.strip().lower() for u in os.getenv("FECHAMENTO_USERS", "").split(",") if u.strip()]

def show_fechamento_for(user) -> bool:
    if not user or not getattr(user, "username", None):
        return False
    return user.username.lower() in FECHAMENTO_USERS        

# --- AUTENTICAÇÃO E ROTAS DE PÁGINAS ---
@app.exception_handler(StarletteHTTPException)
async def auth_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse("/login")
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)

def get_db_session():
    """Cria e fornece uma sessão de banco de dados para uma rota."""
    with Session(engine) as session:
        yield session

def get_current_user(request: Request, session: Session = Depends(get_db_session)) -> User:
    """
    Pega o ID do usuário da sessão, busca o usuário no banco
    e o retorna. Lança uma exceção se não estiver logado.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    user = session.get(User, user_id)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    return user

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

def verify_action_permission(user: User = Depends(get_current_user)):
    """
    Dependência RIGOROSA que verifica se o usuário pode EXECUTAR uma ação.
    Acesso é permitido se o usuário for:
    1. O administrador principal.
    2. Tiver o plano vitalício (plano_ilimitado).
    3. Tiver uma data de expiração válida no futuro.
    """
    # 1. Pega o nome do administrador do arquivo .env para a verificação
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")

    # 2. Permite o acesso imediato se for o admin ou tiver plano vitalício
    if user.username == admin_user_env or user.plano_ilimitado:
        return user

    # 3. Verifica se existe uma data de expiração
    if user.data_expiracao:
        # Compara a data de expiração com a data e hora atuais (com fuso horário)
        if user.data_expiracao > datetime.now(timezone.utc):
            return user # A data é válida, permite o acesso

    # 4. Se nenhuma das condições acima for atendida, o acesso é bloqueado.
    pix_message = "Para continuar usando, realize o pagamento. Chave PIX (Celular): 19971351371. Valor: R$ 100,00. Após o pagamento, contate o administrador."
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, 
        detail=f"Sua assinatura expirou. Não é possível salvar ou atualizar orçamentos. {pix_message}"
    )

def verify_page_access(user: User = Depends(get_current_user)):
    """
    Dependência que apenas verifica se o usuário está logado para permitir
    a VISUALIZAÇÃO de uma página, sem bloquear por status de assinatura.
    O bloqueio de ações ocorrerá em suas respectivas rotas.
    """
    # A própria dependência get_current_user já garante que o usuário existe e está logado.
    # Se chegamos aqui, é porque ele pode ver a página.
    return user

@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    with Session(engine) as session:
        # 1. Busca o usuário pelo username fornecido no formulário
        statement = select(User).where(User.username == username)
        user = session.exec(statement).first()

        # 2. Verifica se o usuário existe E se a senha digitada corresponde à senha criptografada
        if user and verify_password(password, user.hashed_password):
            # Se tudo estiver correto, armazena o ID e o username do usuário na sessão
            request.session["user_id"] = user.id
            request.session["user_username"] = user.username
            print(f"Login bem-sucedido para o usuário: {user.username}")
            return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    # Se o usuário não existir ou a senha estiver incorreta, redireciona para a página de login com erro
    print(f"Falha no login para o usuário: {username}")
    return RedirectResponse(url="/login?error=true", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": current_user, "show_fechamento": show_fechamento_for(current_user), "tem_funcao_analise_custo": current_user.tem_funcao_analise_custo})

@app.get("/orcamentos", response_class=HTMLResponse)
async def orcamentos_page(request: Request, current_user: User = Depends(verify_page_access)):
    admin_username = os.getenv("BASIC_AUTH_USER", "admin")

    # Pega a lista de modelos (exceto o 'default') para enviar ao template
    available_templates = {key: key.capitalize() for key in PDF_GENERATORS if key != 'default'}

    return templates.TemplateResponse(
        "orcamentos.html", 
        {
            "request": request, 
            "user": current_user, 
            "admin_username_from_env": admin_username,
            "pdf_templates": available_templates 
        }
    )


# --- ROTAS DA API ---

@app.post("/salvar-orcamento/")
async def salvar_orcamento_endpoint(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(verify_action_permission)  
):
    
    form_data = await request.form()
    
    cliente_id_str = form_data.get("cliente_id")
    nome_cliente = form_data.get("nome")
    salvar_cliente_flag = form_data.get("salvar_cliente") == "on"
    contatos_json = form_data.get("contatos", "[]") 
    contatos_data = json.loads(contatos_json)

    cliente_para_orcamento = None
    cliente_id_para_orcamento = None

    if cliente_id_str and salvar_cliente_flag:
        cliente_existente = session.get(Cliente, int(cliente_id_str))
        if not cliente_existente or cliente_existente.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Cliente selecionado inválido.")
        
        # ATUALIZA os dados do cliente existente com o que veio do formulário
        cliente_existente.nome = form_data.get("nome")
        cliente_existente.telefone = form_data.get("telefone")
        cliente_existente.cep = form_data.get("cep")
        cliente_existente.logradouro = form_data.get("logradouro")
        cliente_existente.numero_casa = form_data.get("numero_casa")
        cliente_existente.complemento = form_data.get("complemento")
        cliente_existente.bairro = form_data.get("bairro")
        cliente_existente.cidade_uf = form_data.get("cidade_uf")

        # Apaga os contatos antigos e recria com a nova lista (mesma lógica da tela de edição)
        for contato in cliente_existente.contatos:
            session.delete(contato)
        
        for contato_info in contatos_data:
            session.add(Contato(
                nome=contato_info['nome'],
                telefone=contato_info['telefone'],
                email=contato_info.get('email'),
                cliente_id=cliente_existente.id
            ))
        
        session.add(cliente_existente)
        session.commit()

        if current_user.contador_orcamento_override is not None:
            current_user.contador_orcamento_override = None
            session.add(current_user)
            session.commit()
            
        session.refresh(cliente_existente)
        
        cliente_para_orcamento = cliente_existente
        cliente_id_para_orcamento = cliente_existente.id

    # CASO 2: Um cliente NOVO está sendo criado e salvo
    elif not cliente_id_str and nome_cliente and salvar_cliente_flag:
        cliente_novo = Cliente(
            nome=nome_cliente,
            telefone=form_data.get("telefone"),
            cep=form_data.get("cep"),
            logradouro=form_data.get("logradouro"),
            numero_casa=form_data.get("numero_casa"),
            complemento=form_data.get("complemento"),
            bairro=form_data.get("bairro"),
            cidade_uf=form_data.get("cidade_uf"),
            user_id=current_user.id
        )
        session.add(cliente_novo)
        session.commit() # Salva o cliente para obter um ID
        session.refresh(cliente_novo)

        # Agora cria os contatos vinculados ao novo cliente
        for contato_info in contatos_data:
            session.add(Contato(
                nome=contato_info['nome'],
                telefone=contato_info['telefone'],
                email=contato_info.get('email'),
                cliente_id=cliente_novo.id
            ))

        session.commit()
        session.refresh(cliente_novo)

        cliente_para_orcamento = cliente_novo
        cliente_id_para_orcamento = cliente_novo.id

    # CASO 3: Um cliente existente foi selecionado, mas NENHUMA alteração foi feita/salva
    elif cliente_id_str:
        cliente_para_orcamento = session.get(Cliente, int(cliente_id_str))
        cliente_id_para_orcamento = cliente_para_orcamento.id    

    # --- LÓGICA DO ORÇAMENTO (como já estava)
    itens_data = json.loads(form_data.get("itens"))
    total_geral = sum(int(i['quantidade']) * float(i['valor']) for i in itens_data)

    condicao_pagamento = form_data.get("condicao_pagamento")
    try:
        # Tenta carregar como JSON; se for uma lista/dicionário, converte para string
        parsed_json = json.loads(condicao_pagamento)
        condicao_pagamento_final = json.dumps(parsed_json)
    except (json.JSONDecodeError, TypeError):
        # Se falhar, é uma string simples ou nulo
        condicao_pagamento_final = condicao_pagamento or "A combinar"

    
    orcamento_db = Orcamento(
        numero=form_data.get("numero_orcamento"),
        descricao_servico=form_data.get("descricao_servico"),
        itens=itens_data,
        total_geral=total_geral,
        data_emissao=datetime.now().strftime('%d/%m/%Y'),
        data_validade=(datetime.now() + timedelta(days=7)).strftime('%d/%m/%Y'),
        user_id=current_user.id,
        cliente_id=cliente_id_para_orcamento,

        nome_cliente=form_data.get("nome"),
        telefone_cliente=form_data.get("telefone"),
        cep_cliente=form_data.get("cep"),
        logradouro_cliente=form_data.get("logradouro"),
        numero_casa_cliente=form_data.get("numero_casa"),
        complemento_cliente=form_data.get("complemento"),
        bairro_cliente=form_data.get("bairro"),
        cidade_uf_cliente=form_data.get("cidade_uf"),
        condicao_pagamento=condicao_pagamento_final,
        prazo_entrega=form_data.get("prazo_entrega"),
        garantia=form_data.get("garantia"),
        observacoes=form_data.get("observacoes"),
    )

    contatos_json = form_data.get("contatos", "[]") 
    contatos_data = json.loads(contatos_json)

    for contato_info in contatos_data:
        contato_orc = ContatoOrcamento(
            nome=contato_info['nome'],
            telefone=contato_info['telefone'],
            email=contato_info.get('email')
        )
        orcamento_db.contatos_extras.append(contato_orc)

    session.add(orcamento_db)
    session.commit()

    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    # A verificação só se aplica se o usuário não for admin e não tiver plano vitalício
    if current_user.username != admin_user_env and not current_user.plano_ilimitado and current_user.data_expiracao:
        dias_restantes = (current_user.data_expiracao - datetime.now(timezone.utc)).days
        
        # Se faltam 3 dias ou menos para expirar, envia uma resposta de "sucesso com aviso"
        if 0 <= dias_restantes <= 3:
            pix_message = "Para renovar, pague o valor e contate o administrador. Chave PIX (Celular): 19971351371. Valor: R$ 100,00."
            return JSONResponse(
                status_code=200,
                content={
                    "status": "warning", 
                    "message": f"Orçamento salvo! Atenção: seu acesso expira em {dias_restantes + 1} dia(s). {pix_message}"
                }
            )

    # Se não houver aviso, envia a resposta de sucesso padrão
    return JSONResponse(
        status_code=200,
        content={"status": "success", "message": "Orçamento salvo com sucesso!"}
    )

# Função para atualizar a data de expiração após pagamento
def atualizar_data_expiracao(user: User, session: Session):
    user.data_expiracao = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    user.totens = 3  # Restaurar os 3 créditos
    session.add(user)
    session.commit()

@app.get("/api/orcamentos/")
def listar_orcamentos_api(
    user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    statement = (
        select(Orcamento)
        .where(Orcamento.user_id == user.id)
        .order_by(Orcamento.id.desc())
    )
    orcamentos = session.exec(statement).all()
    resultado = []
    for o in orcamentos:
        
        # --- LÓGICA DE CÁLCULO ADICIONADA ---
        total_servicos = 0
        total_materiais = 0
        # O campo 'itens' é um JSON, então o tratamos como um dicionário
        for item in o.itens:
            # Garantimos que os campos existem e são numéricos
            quantidade = int(item.get('quantidade', 0))
            valor = float(item.get('valor', 0))
            
            if item.get('tipo') == 'servico':
                total_servicos += quantidade * valor
            elif item.get('tipo') == 'material':
                total_materiais += quantidade * valor
        # --- FIM DA LÓGICA ---
        
        resultado.append({
            "id": o.id,
            "numero": o.numero,
            "nome": o.nome_cliente,
            "data_emissao": o.data_emissao,
            "total_geral": o.total_geral,
            "telefone": o.telefone_cliente,
            "total_servicos": total_servicos,       # <- Novo campo
            "total_materiais": total_materiais,     # <- Novo campo
        })
    return resultado

@app.get("/api/orcamento-detalhes/{orcamento_id}")
def get_orcamento_detalhes(
    orcamento_id: int,
    user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    """ Busca os detalhes de um único orçamento para garantir dados atualizados. """
    orcamento = session.get(Orcamento, orcamento_id)
    
    if not orcamento or orcamento.user_id != user.id:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    
    # Reutilizamos a mesma lógica de cálculo da lista para consistência
    total_servicos = 0
    total_materiais = 0
    for item in orcamento.itens:
        quantidade = int(item.get('quantidade', 0))
        valor = float(item.get('valor', 0))
        if item.get('tipo') == 'servico':
            total_servicos += quantidade * valor
        elif item.get('tipo') == 'material':
            total_materiais += quantidade * valor
            
    return {
        "id": orcamento.id,
        "numero": orcamento.numero,
        "total_geral": orcamento.total_geral,
        "total_servicos": total_servicos,
        "total_materiais": total_materiais,
    }


# --- ROTAS DA API PARA ITENS DE CATÁLOGO ---
@app.post("/api/item/", response_model=Item, status_code=status.HTTP_201_CREATED)
def create_item(
    item: Item,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    statement = select(Item).where(
        func.lower(Item.nome) == func.lower(item.nome),
        Item.tipo == item.tipo,
        Item.user_id == current_user.id
    )
    existing_item = session.exec(statement).first()

    if existing_item:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"O item '{item.nome}' já existe no catálogo de {item.tipo}s."
        )

    item.user_id = current_user.id
    session.add(item)
    session.commit()
    session.refresh(item)
    return item



@app.get("/api/servico/", response_model=List[Item])
def read_servicos(current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    
    statement = select(Item).where(Item.tipo == "servico", Item.user_id == current_user.id)
    return session.exec(statement).all()

@app.get("/api/materiais/", response_model=List[Item])
def read_materiais(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    statement = select(Item).where(Item.tipo == "material", Item.user_id == current_user.id)
    return session.exec(statement).all()

@app.delete("/api/item/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item não encontrado")
        session.delete(item)
        session.commit()
        return
    
@app.get("/orcamento/{orcamento_id}/pdf", response_class=StreamingResponse)
async def gerar_e_salvar_pdf_protegido(
    orcamento_id: int,
    status: str = Query("Orçamento"), 
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """
    ESTA ROTA É PROTEGIDA. Apenas o usuário logado pode gerar/regenerar o PDF e o token.
    """
    statement = select(Orcamento).where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    
    orcamento.status = status 
    
    # GARANTE QUE UM TOKEN SECRETO E ÚNICO SEMPRE EXISTA
    if not orcamento.token_visualizacao:
        orcamento.token_visualizacao = secrets.token_urlsafe(16)
        session.add(orcamento)
        session.commit()
        session.refresh(orcamento)
        
    user = session.get(User, orcamento.user_id)
    template_name = user.pdf_template_name
    pdf_function = PDF_GENERATORS.get(template_name, PDF_GENERATORS["default"])
    
    pdf_buffer = io.BytesIO()
    pdf_function(file_path=pdf_buffer, orcamento=orcamento)
    pdf_bytes = pdf_buffer.getvalue()

    nome_arquivo = f"{orcamento.status.replace(' ', '_')}_{orcamento.numero}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'}
    )

@app.get("/orcamento/{orcamento_id}/relatorio-custo", response_class=StreamingResponse)
async def gerar_pdf_relatorio_custo_endpoint(
    orcamento_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """
    GERA O PDF DE RELATÓRIO DE CUSTO INTERNO.
    Apenas o usuário com a permissão pode acessar.
    """
    if not current_user.tem_funcao_analise_custo:
        raise HTTPException(status_code=403, detail="Acesso não autorizado.")
    
    statement = select(Orcamento).where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    
    # Verifica se a análise já foi preenchida
    if orcamento.valor_obra_total is None:
         raise HTTPException(status_code=400, detail="A análise de custo para este orçamento ainda não foi preenchida.")

    pdf_buffer = io.BytesIO()
    gerar_pdf_relatorio_custo(file_path=pdf_buffer, orcamento=orcamento)
    pdf_bytes = pdf_buffer.getvalue()

    nome_arquivo = f"Relatorio_Custo_Orc_{orcamento.numero}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'}
    )

@app.get("/orcamento/publico/{token}", response_class=StreamingResponse)
async def get_pdf_publico(token: str, status: str = Query("Orçamento"), session: Session = Depends(get_db_session)):
    """
    ESTA É A ROTA PÚBLICA QUE O CLIENTE USA. ELA SÓ FUNCIONA COM O TOKEN.
    """
    statement = select(Orcamento).where(Orcamento.token_visualizacao == token)
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Not Found") # Mensagem genérica por segurança
    
    orcamento.status = status

    user = session.get(User, orcamento.user_id)
    template_name = user.pdf_template_name
    pdf_function = PDF_GENERATORS.get(template_name, PDF_GENERATORS["default"])

    pdf_buffer = io.BytesIO()
    pdf_function(file_path=pdf_buffer, orcamento=orcamento)
    pdf_bytes = pdf_buffer.getvalue()
    
    nome_arquivo = f"Orcamento_{orcamento.numero}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'}
    )

@app.get("/orcamento/{orcamento_id}/whatsapp")
def gerar_link_whatsapp(
    orcamento_id: int, 
    request: Request,
    status: str = Query("Orçamento"), 
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    print("STATUS RECEBIDO NO BACKEND:", status)
    
    orcamento = session.get(Orcamento, orcamento_id)
    if not orcamento or orcamento.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

    if not orcamento.token_visualizacao:
        raise HTTPException(status_code=400, detail="Por favor, clique no ícone de PDF primeiro para gerar o link de compartilhamento.")
        
    pdf_url = f"{str(request.base_url)}orcamento/publico/{orcamento.token_visualizacao}?status={quote(status)}"
    
    nome_cliente = orcamento.cliente.nome if orcamento.cliente else orcamento.nome_cliente

    if status == "Nota de Serviço":
        mensagem = (
            f"Olá, {nome_cliente}!\n\n"
            f"Segue a sua *Nota de Serviço* nº *{orcamento.numero}* referente ao serviço finalizado.\n\n"
            f"Você pode visualizar o documento completo no link abaixo:\n"
            f"{pdf_url}\n\n"
            f"Muito obrigado pela confiança!"
        )
    else:
        mensagem = (
            f"Olá, {nome_cliente}!\n\n"
            f"Segue o seu *Orçamento* nº *{orcamento.numero}*.\n\n"
            f"Você pode visualizar o documento completo no link abaixo:\n"
            f"{pdf_url}\n\n"
            f"Qualquer dúvida, estou à disposição!"
        )

    # NÃO FAÇA O ENCODE AQUI!
    return JSONResponse(content={"whatsapp_message": mensagem})

@app.get("/editar-orcamento/{orcamento_id}", response_class=HTMLResponse)
async def editar_orcamento_page(
    orcamento_id: int, 
    request: Request, 
    current_user: User = Depends(verify_page_access),
    session: Session = Depends(get_db_session) # Usa a sessão da dependência
):
    # USAREMOS selectinload PARA GARANTIR QUE O CLIENTE VENHA JUNTO
    statement = (
        select(Orcamento)
        .options(
            selectinload(Orcamento.contatos_extras),
        selectinload(Orcamento.cliente).selectinload(Cliente.contatos)
        )
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    )
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    
    # O resto do seu código já estava correto
    return templates.TemplateResponse(
        "editar_orcamento.html", 
        {"request": request, "user": current_user, "orcamento": orcamento, "show_fechamento": show_fechamento_for(current_user),"tem_funcao_analise_custo": current_user.tem_funcao_analise_custo}
    )

# SUBSTITUA A FUNÇÃO ATUALIZAR INTEIRA POR ESTA:
# Em app.py, SUBSTITUA a função de atualizar inteira por esta:

@app.post("/atualizar-orcamento/{orcamento_id}")
async def atualizar_orcamento_submit(
    request: Request,
    orcamento_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(verify_action_permission)
):
    form_data = await request.form()
    
    # Busca o orçamento e seus relacionamentos (SEU CÓDIGO JÁ ESTÁ CORRETO AQUI)
    orcamento_db = session.exec(
        select(Orcamento).options(
            selectinload(Orcamento.contatos_extras), 
            selectinload(Orcamento.cliente).selectinload(Cliente.contatos)
        )
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    ).first()
    
    if not orcamento_db:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado para atualizar")

    # Atualiza dados de cliente/fallback (SEU CÓDIGO JÁ ESTÁ CORRETO AQUI)
    orcamento_db.nome_cliente = form_data.get("nome")
    orcamento_db.telefone_cliente = form_data.get("telefone")
    orcamento_db.cep_cliente = form_data.get("cep")
    orcamento_db.logradouro_cliente = form_data.get("logradouro")
    orcamento_db.numero_casa_cliente = form_data.get("numero_casa")
    orcamento_db.complemento_cliente = form_data.get("complemento")
    orcamento_db.bairro_cliente = form_data.get("bairro")
    orcamento_db.cidade_uf_cliente = form_data.get("cidade_uf")

    salvar_cliente_flag = form_data.get("salvar_cliente") == "on"

    # Sincroniza com perfil do cliente (SEU CÓDIGO JÁ ESTÁ CORRETO AQUI)
    if orcamento_db.cliente and salvar_cliente_flag:
        cliente = orcamento_db.cliente
        cliente.nome = form_data.get("nome")
        cliente.telefone = form_data.get("telefone")
        cliente.cep = form_data.get("cep")
        cliente.logradouro = form_data.get("logradouro")
        cliente.numero_casa = form_data.get("numero_casa")
        cliente.complemento = form_data.get("complemento")
        cliente.bairro = form_data.get("bairro")
        cliente.cidade_uf = form_data.get("cidade_uf")
        cliente.contatos.clear()
        contatos_data = json.loads(form_data.get("contatos", "[]"))

        for c_info in contatos_data:
            cliente.contatos.append(Contato(nome=c_info['nome'], telefone=c_info['telefone'], email=c_info.get('email')))
        session.add(cliente)
    
    # Atualiza dados do orçamento (SEU CÓDIGO JÁ ESTÁ CORRETO AQUI)
    orcamento_db.numero = form_data.get("numero_orcamento").strip()
    orcamento_db.descricao_servico = form_data.get("descricao_servico")
    itens_data = json.loads(form_data.get("itens"))
    orcamento_db.itens = itens_data
    orcamento_db.total_geral = sum(int(i.get('quantidade', 0)) * float(i.get('valor', 0)) for i in itens_data)
    
    # **** AQUI ESTÁ A ÚNICA CORREÇÃO NECESSÁRIA ****
    # O valor que vem do formulário já é a string JSON correta.
    # Não precisamos tentar fazer `json.loads` de novo.
    # Apenas pegamos o valor e o salvamos.
    orcamento_db.condicao_pagamento = form_data.get("condicao_pagamento")

    # O resto continua correto
    orcamento_db.prazo_entrega = form_data.get("prazo_entrega")
    orcamento_db.garantia = form_data.get("garantia")
    orcamento_db.observacoes = form_data.get("observacoes")

    # Atualiza contatos do orçamento (SEU CÓDIGO JÁ ESTÁ CORRETO AQUI)
    orcamento_db.contatos_extras.clear()
    contatos_data_orc = json.loads(form_data.get("contatos", "[]"))
    for c_info in contatos_data_orc:
        orcamento_db.contatos_extras.append(ContatoOrcamento(nome=c_info['nome'], telefone=c_info['telefone'], email=c_info.get('email')))
    
    session.add(orcamento_db)
    session.commit()
    
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env and not current_user.plano_ilimitado and current_user.data_expiracao:
        dias_restantes = (current_user.data_expiracao - datetime.now(timezone.utc)).days
        
        if 0 <= dias_restantes <= 3:
            pix_message = "Para renovar, pague e contate o administrador. Chave PIX (Celular): 19971351371. Valor: R$ 100,00."
            return JSONResponse(
                status_code=200,
                content={
                    "status": "warning", 
                    "message": f"Orçamento atualizado! Atenção: seu acesso expira em {dias_restantes + 1} dia(s). {pix_message}"
                }
            )

    # Se não houver aviso, envia a resposta de sucesso padrão que o JavaScript irá usar para redirecionar.
    return JSONResponse(
        status_code=200,
        content={"status": "success", "message": "Orçamento atualizado com sucesso!"}
    )


@app.delete("/api/orcamentos/{orcamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_orcamento(
    orcamento_id: int, 
    current_user: User = Depends(get_current_user), # <-- Adiciona dependência
    session: Session = Depends(get_db_session)      # <-- Adiciona dependência
):
    orcamento = session.get(Orcamento, orcamento_id)
    if not orcamento:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orçamento não encontrado")
    
    # --- VERIFICAÇÃO DE PERMISSÃO ---
    if orcamento.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")
        
    session.delete(orcamento)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/orcamento/{orcamento_id}/analise-custo", status_code=status.HTTP_200_OK)
def get_dados_analise_custo(
    orcamento_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """
    Busca e retorna os dados da análise de custo de um orçamento específico,
    se eles existirem.
    """
    # Verifica se o usuário tem a permissão para usar a função
    if not current_user.tem_funcao_analise_custo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para acessar esta funcionalidade."
        )

    orcamento = session.get(Orcamento, orcamento_id)
    
    # Verifica se o orçamento existe e se pertence ao usuário logado
    if not orcamento or orcamento.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orçamento não encontrado.")
    
    # Retorna apenas os campos relevantes em um dicionário
    return {
        "valor_obra_total": orcamento.valor_obra_total,
        "percentual_imposto_servico": orcamento.percentual_imposto_servico,
        "percentual_imposto_material": orcamento.percentual_imposto_material,
        "custo_mao_de_obra": orcamento.custo_mao_de_obra,
        "custo_materiais": orcamento.custo_materiais,
        "despesas_extras": orcamento.despesas_extras or [],
    }

@app.get("/api/proximo-numero/")
def get_proximo_numero(response: Response, current_user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    
    override_base = current_user.contador_orcamento_override
    if override_base is not None:
        proximo_numero_final = override_base + 1
        return {"proximo_numero": str(proximo_numero_final).zfill(4)}

    # Se não há override, faz a lógica normal do banco
    ultimo_orcamento_db = session.exec(
        select(Orcamento).where(Orcamento.user_id == current_user.id).order_by(cast(Orcamento.numero, Integer).desc())
    ).first()
    proximo_numero_natural = (int(ultimo_orcamento_db.numero) + 1) if ultimo_orcamento_db and ultimo_orcamento_db.numero.isdigit() else 1
    return {"proximo_numero": str(proximo_numero_natural).zfill(4)}
    
@app.post("/api/resetar-contador/")
async def resetar_contador_endpoint(
    novo_inicio: int = Form(...),
    current_user: User = Depends(get_current_user), # Pega o usuário logado
    session: Session = Depends(get_db_session)      # Pega a sessão do banco
):
    """
    Redefine o contador de orçamentos para um novo valor inicial para o usuário logado.
    """
    if novo_inicio < 0:
        raise HTTPException(status_code=400, detail="O número inicial não pode ser negativo.")
    
    # Salva o novo valor no campo do usuário
    current_user.contador_orcamento_override = novo_inicio
    session.add(current_user)
    session.commit()
    
    proximo_numero = novo_inicio + 1
    return {"message": f"Contador reiniciado com sucesso. O próximo número será {str(proximo_numero).zfill(4)}."}

@app.post("/api/users/", status_code=status.HTTP_201_CREATED)
def create_user(
    username: str = Form(...),
    password: str = Form(...),
    pdf_template_name: str = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user) 
):
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    # Opcional: Adicionar uma verificação para que apenas o 'admin' possa criar usuários
    if current_user.username != admin_user_env:
        raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN, 
             detail="Apenas o administrador pode criar novos usuários."
        )

    # Verifica se o nome de usuário já existe
    user_in_db = session.exec(select(User).where(User.username == username)).first()
    if user_in_db:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nome de usuário já cadastrado.")

    # Criptografa a senha e cria o novo usuário
    hashed_password = get_password_hash(password)
    new_user = User(username=username, hashed_password=hashed_password, pdf_template_name=pdf_template_name)

    session.add(new_user)
    session.commit()
    
    return {"message": f"Usuário '{username}' criado com sucesso!"}

def get_orcamento_do_usuario(session, orcamento_id, user_id):
    orcamento = session.exec(
        select(Orcamento).where(Orcamento.id == orcamento_id, Orcamento.user_id == user_id)
    ).first()
    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    return orcamento

class ContatoResponse(BaseModel):
    id: Optional[int] = None
    nome: str
    telefone: str
    email: Optional[str] = None

class ClienteComContatosResponse(BaseModel):
    id: Optional[int]
    nome: str
    telefone: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero_casa: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade_uf: Optional[str] = None
    contatos: List[ContatoResponse] = []

class ContatoUpdate(BaseModel):
    id: Optional[int] = None
    nome: str
    telefone: str
    email: Optional[str] = None

class ClienteUpdate(BaseModel):
    nome: str
    telefone: Optional[str] = None
    cep: Optional[str] = None
    logradouro: Optional[str] = None
    numero_casa: Optional[str] = None
    complemento: Optional[str] = None
    bairro: Optional[str] = None
    cidade_uf: Optional[str] = None
    contatos: List[ContatoUpdate] = []
    
class DespesaExtraItem(BaseModel):
    descricao: str
    valor: float    

class AnaliseCustoUpdate(BaseModel):
    valor_obra_total: float
    percentual_imposto_servico: float
    percentual_imposto_material: float
    custo_mao_de_obra: float
    custo_materiais: float 
    despesas_extras: List[DespesaExtraItem] = [] 



# --- ROTAS DA API PARA CLIENTES ---
# SUBSTITUA esta função de API inteira no app.py

@app.get("/api/orcamento/{orcamento_id}/contatos", response_model=List[ContatoResponse])
def get_orcamento_contatos(
    orcamento_id: int, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    """
    Busca um orçamento pelo ID e retorna uma lista limpa de contatos 
    (o principal e os extras salvos NO ORÇAMENTO).
    """
    orcamento = session.exec(
        select(Orcamento).options(selectinload(Orcamento.contatos_extras)) # Só precisamos carregar os contatos do orçamento
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    ).first()
    
    if not orcamento:
        return []

    telefones_adicionados = set()
    contatos_unicos = []

    # 1. Adiciona o contato principal (o que foi salvo/digitado para o orçamento)
    if orcamento.telefone_cliente:
        telefone_normalizado = "".join(filter(str.isdigit, orcamento.telefone_cliente))
        if telefone_normalizado and telefone_normalizado not in telefones_adicionados:
            contatos_unicos.append(
                ContatoResponse(id=None, nome=orcamento.nome_cliente, telefone=orcamento.telefone_cliente)
            )
            telefones_adicionados.add(telefone_normalizado)
        
    # 2. Adiciona os contatos extras que foram salvos COM o orçamento
    for contato in orcamento.contatos_extras:
        telefone_normalizado = "".join(filter(str.isdigit, contato.telefone))
        if telefone_normalizado and telefone_normalizado not in telefones_adicionados:
            contatos_unicos.append(
                ContatoResponse(id=contato.id, nome=contato.nome, telefone=contato.telefone, email=contato.email)
            )
            telefones_adicionados.add(telefone_normalizado)
            
    return contatos_unicos

@app.post("/api/orcamento/{orcamento_id}/analise-custo", status_code=status.HTTP_200_OK)
def salvar_dados_analise_custo(
    orcamento_id: int,
    dados: AnaliseCustoUpdate, # Usa o modelo Pydantic para validar os dados
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """
    Salva ou atualiza os dados da análise de custo de um orçamento.
    """
    if not current_user.tem_funcao_analise_custo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para salvar estas informações."
        )
        
    orcamento_db = session.get(Orcamento, orcamento_id)
    if not orcamento_db or orcamento_db.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orçamento não encontrado.")
    
    # Atualiza os campos do orçamento com os dados recebidos
    orcamento_db.valor_obra_total = dados.valor_obra_total
    orcamento_db.percentual_imposto_servico = dados.percentual_imposto_servico
    orcamento_db.percentual_imposto_material = dados.percentual_imposto_material
    orcamento_db.custo_mao_de_obra = dados.custo_mao_de_obra
    orcamento_db.custo_materiais = dados.custo_materiais
    orcamento_db.despesas_extras = [item.model_dump() for item in dados.despesas_extras]

    # --- RECÁLCULO DO LUCRO COM IMPOSTOS SEPARADOS ---
    # 1. Pega os totais brutos de serviços e materiais dos itens do orçamento
    total_servicos_bruto = sum(item['valor'] * item['quantidade'] for item in orcamento_db.itens if item['tipo'] == 'servico')
    total_materiais_bruto = sum(item['valor'] * item['quantidade'] for item in orcamento_db.itens if item['tipo'] == 'material')
    
    # 2. Calcula o valor de cada imposto separadamente
    valor_imposto_servico = total_servicos_bruto * (dados.percentual_imposto_servico / 100)
    valor_imposto_material = total_materiais_bruto * (dados.percentual_imposto_material / 100)
    
    # 3. Calcula o valor líquido subtraindo ambos impostos da receita bruta total
    receita_liquida = dados.valor_obra_total - valor_imposto_servico - valor_imposto_material
    
    # 4. Calcula os custos
    custo_despesas = sum(item.valor for item in dados.despesas_extras)
    custo_total = dados.custo_mao_de_obra + dados.custo_materiais + custo_despesas
    
    # 5. Calcula o lucro final
    lucro_bruto = receita_liquida - custo_total
    
    orcamento_db.lucro_previsto = lucro_bruto
    orcamento_db.valor_dizimo = lucro_bruto * 0.10 if lucro_bruto > 0 else 0

    session.add(orcamento_db)
    session.commit()
    
    return {"message": "Análise de custo salva com sucesso!"}


@app.get("/api/clientes/", response_model=List[ClienteComContatosResponse]) 
def listar_clientes_api(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    """Retorna uma lista de todos os clientes associados ao usuário logado."""
    clientes = session.exec(
        select(Cliente).options(selectinload(Cliente.contatos)).where(Cliente.user_id == current_user.id).order_by(Cliente.nome) # <--- CORREÇÃO APLICADA
    ).all()
    return clientes

@app.get("/api/clientes/{cliente_id}", response_model=ClienteComContatosResponse)
def obter_cliente_api(
    cliente_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    """Retorna os dados de um cliente específico, verificando se ele pertence ao usuário logado."""
    cliente = session.exec(
    select(Cliente).options(selectinload(Cliente.contatos)).where(Cliente.id == cliente_id, Cliente.user_id == current_user.id)
    ).first()
    
    if not cliente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Cliente não encontrado ou não pertence a este usuário."
        )
    
    return cliente

@app.delete("/api/clientes/{cliente_id}", status_code=204)
def deletar_cliente(
    cliente_id: int = Path(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    cliente = session.get(Cliente, cliente_id)
    if not cliente or cliente.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    session.delete(cliente)
    session.commit()
    return Response(status_code=204)

@app.put("/api/clientes/{cliente_id}", response_model=ClienteComContatosResponse)
def atualizar_cliente(
    cliente_id: int,
    cliente_update_data: ClienteUpdate,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """
    Atualiza um cliente e seus contatos associados.
    """
    # Busca o cliente existente no banco, garantindo que ele pertença ao usuário logado
    cliente_db = session.exec(
        select(Cliente)
        .options(selectinload(Cliente.contatos)) # Carrega os contatos existentes para edição
        .where(Cliente.id == cliente_id, Cliente.user_id == current_user.id)
    ).first()

    if not cliente_db:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")

    update_data = cliente_update_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key != "contatos": # O campo 'contatos' será tratado separadamente
            setattr(cliente_db, key, value)


 
    contatos_recebidos = {c.id for c in cliente_update_data.contatos if c.id}
    contatos_no_banco = {c.id for c in cliente_db.contatos}
    
    # Apaga contatos que não vieram na lista
    for contato in list(cliente_db.contatos):
        if contato.id not in contatos_recebidos:
            session.delete(contato)

    # Atualiza contatos existentes ou cria novos
    for contato_data in cliente_update_data.contatos:
        if contato_data.id: # Se tem ID, atualiza
            contato_existente = session.get(Contato, contato_data.id)
            if contato_existente:
                contato_existente.nome = contato_data.nome
                contato_existente.telefone = contato_data.telefone
                contato_existente.email = contato_data.email
        else: # Se não tem ID, cria um novo
            novo_contato = Contato(
                nome=contato_data.nome,
                telefone=contato_data.telefone,
                email=contato_data.email,
                cliente_id=cliente_db.id
            )
            session.add(novo_contato)

    session.add(cliente_db)
    session.commit()
    session.refresh(cliente_db)

    return cliente_db

@app.post("/orcamento/{orcamento_id}/email/link")
def gerar_link_email(
    orcamento_id: int,
    request: Request,
    destinatario: str = Form(""),
    status: str = Query("Orçamento"),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    statement = (
        select(Orcamento)
        .options(selectinload(Orcamento.cliente))
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    )
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    
    # MESMA LÓGICA DO WHATSAPP: VERIFICA SE O TOKEN EXISTE
    if not orcamento.token_visualizacao:
        raise HTTPException(
            status_code=400, 
            detail="Por favor, clique no ícone de PDF primeiro para gerar o link de compartilhamento."
        )
    
    # USA O TOKEN PARA CRIAR O LINK PÚBLICO E SEGURO
    pdf_url = f"{str(request.base_url).replace('http://', 'https://')}orcamento/publico/{orcamento.token_visualizacao}?status={quote(status)}"

    nome_cliente = orcamento.cliente.nome if orcamento.cliente else orcamento.nome_cliente

    # Lógica condicional para personalizar a mensagem
    if status == "Nota de Serviço":
        assunto = f"Nota de Serviço #{str(orcamento.numero).zfill(4)}"
        corpo_email = f"""Olá {nome_cliente},

    Segue a sua nota de serviço de número #{str(orcamento.numero).zfill(4)}, referente ao trabalho finalizado.

    Visualize o documento completo no link abaixo:
    {pdf_url}

    Agradecemos pela preferência!"""
    else: # Padrão para "Orçamento"
        assunto = f"Orçamento #{str(orcamento.numero).zfill(4)}"
        corpo_email = f"""Olá {nome_cliente},

    Conforme solicitado, segue o seu orçamento de número #{str(orcamento.numero).zfill(4)}.

    Visualize o documento completo no link abaixo:
    {pdf_url}

    Qualquer dúvida, estou à disposição."""
    
    assunto_codificado = quote(assunto)
    corpo_codificado = quote(corpo_email)
    mailto_link = f"mailto:{destinatario}?subject={assunto_codificado}&body={corpo_codificado}"
    
    return {"mailto_link": mailto_link}

@app.post("/api/user/update-template")
def update_user_template(
    new_template: str = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    # 1. Pega o nome do usuário administrador a partir do arquivo .env
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")

    # 2. VERIFICAÇÃO DE PERMISSÃO: Apenas o admin pode usar esta rota
    if current_user.username != admin_user_env:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o administrador pode alterar o modelo de PDF."
        )

    # 3. Verifica se o template enviado é válido
    if new_template not in PDF_GENERATORS:
        raise HTTPException(status_code=400, detail="Modelo de PDF inválido.")

    # 4. Atualiza o campo no objeto do usuário administrador
    current_user.pdf_template_name = new_template
    
    # 5. Adiciona à sessão e salva no banco de dados
    session.add(current_user)
    session.commit()
    
    # 6. Retorna uma mensagem de sucesso
    return {"message": f"Seu modelo de PDF foi atualizado para '{new_template.capitalize()}'!"}

@app.get("/api/users/", response_model=List[User])
def list_users(
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os usuários. Apenas o administrador pode acessar."""
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env:
        raise HTTPException(status_code=403, detail="Acesso negado.")
    
    users = session.exec(select(User)).all()
    return users

class UserAdminView(BaseModel):
    id: int
    username: str
    plano_ilimitado: bool
    data_expiracao: Optional[datetime] # Mantido como string, conforme seu models.py

# Altere a rota /api/users/ para usar o novo modelo e ser mais específica
@app.get("/api/admin/users/", response_model=List[UserAdminView])
def admin_list_users(
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Lista todos os usuários com dados de acesso para o painel de admin."""
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env:
        raise HTTPException(status_code=403, detail="Acesso negado.")
    
    # Exclui o próprio admin da lista de gerenciamento
    users = session.exec(select(User).where(User.username != admin_user_env)).all()
    return users


@app.get("/api/admin/user/{user_id}/status", response_model=UserAdminView)
def admin_get_user_status(
    user_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Obtém o status de acesso de um usuário específico."""
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return user


@app.post("/api/admin/user/update-access")
def admin_update_user_access(
    user_id: int = Form(...),
    action: str = Form(...),
    custom_date: Optional[str] = Form(None), # Novo campo opcional para data
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Atualiza o tipo de acesso de um usuário."""
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    user_to_update = session.get(User, user_id)
    if not user_to_update:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if action == 'lifetime':
        user_to_update.plano_ilimitado = True
        user_to_update.data_expiracao = None
        message = f"Acesso VITALÍCIO concedido a '{user_to_update.username}'."
    elif action == 'monthly':
        user_to_update.plano_ilimitado = False
        user_to_update.data_expiracao = datetime.now(timezone.utc) + timedelta(days=30)
        message = f"Acesso por 30 DIAS liberado para '{user_to_update.username}'."
    
    # --- NOVA LÓGICA PARA DATA PERSONALIZADA ---
    elif action == 'custom_date':
        if not custom_date:
            raise HTTPException(status_code=400, detail="Nenhuma data foi fornecida.")
        try:
            # Converte a data do formulário (YYYY-MM-DD) para um objeto datetime
            # Adiciona a hora para garantir que a validade se estenda até o final do dia
            parsed_date = datetime.strptime(custom_date, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
            user_to_update.plano_ilimitado = False
            user_to_update.data_expiracao = parsed_date
            message = f"A data de expiração de '{user_to_update.username}' foi definida para {parsed_date.strftime('%d/%m/%Y')}."
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD.")
            
    elif action == 'default':
        user_to_update.plano_ilimitado = False
        user_to_update.data_expiracao = None # Isso efetivamente bloqueia o usuário
        message = f"O acesso de '{user_to_update.username}' foi revertido para o padrão (EXPIRADO)."
    else:
        raise HTTPException(status_code=400, detail="Ação inválida.")
        
    session.add(user_to_update)
    session.commit()
    return {"message": message}

@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Apaga um usuário. Apenas o administrador pode e ele não pode se apagar."""
    admin_user_env = os.getenv("BASIC_AUTH_USER", "admin")
    if current_user.username != admin_user_env:
        raise HTTPException(status_code=403, detail="Apenas o administrador pode apagar usuários.")

    user_to_delete = session.get(User, user_id)
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # Medida de segurança: o admin não pode se auto-deletar.
    if user_to_delete.username == admin_user_env:
        raise HTTPException(status_code=400, detail="O administrador não pode apagar a própria conta.")

    session.delete(user_to_delete)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/cliente/verificar/")
def verificar_cliente_existente(
    nome: str = Query(..., min_length=3),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    """
    Verifica se um cliente com um nome específico já existe para o usuário logado.
    A busca não diferencia maiúsculas de minúsculas.
    """
    cliente_existente = session.exec(
        select(Cliente).where(
            func.lower(Cliente.nome) == func.lower(nome),
            Cliente.user_id == current_user.id
        )
    ).first()
    
    if cliente_existente:
        # Se encontrou, retorna o cliente existente para o frontend
        return cliente_existente
    
    # Se não encontrou, retorna um objeto vazio para indicar que o nome está livre
    return {}

@app.get("/api/cliente/verificar/")
def verificar_cliente_existente(
    nome: str = Query(..., min_length=3),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
    """
    Verifica se um cliente com um nome específico já existe para o usuário logado.
    A busca não diferencia maiúsculas de minúsculas.
    """
    cliente_existente = session.exec(
        select(Cliente).where(
            func.lower(Cliente.nome) == func.lower(nome),
            Cliente.user_id == current_user.id
        )
    ).first()
    
    if cliente_existente:
        # Se encontrou, retorna o cliente existente para o frontend
        return cliente_existente
    
    # Se não encontrou, retorna um objeto vazio para indicar que o nome está livre
    return {}

class ContatoEmailResponse(BaseModel):
    nome: str
    email: str

@app.get("/api/orcamento/{orcamento_id}/emails", response_model=List[ContatoEmailResponse])
def get_orcamento_emails(
    orcamento_id: int, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    orcamento = session.exec(
        select(Orcamento).options(selectinload(Orcamento.contatos_extras))
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    ).first()
    if not orcamento: return []
    
    lista_emails = []
    # Percorre apenas os contatos extras e adiciona aqueles que têm e-mail
    for contato in orcamento.contatos_extras:
        if contato.email:
            lista_emails.append(ContatoEmailResponse(nome=contato.nome, email=contato.email))
    
    return lista_emails