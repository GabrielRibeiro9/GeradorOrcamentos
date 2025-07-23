
import os
import httpx
import json
import locale
import secrets
import io
from datetime import datetime, timedelta
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

# --- IMPORTS DO CLOUDINARY (MOVA ELES PARA CÁ) ---
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- Import dos seus modelos de dados ---
from models import Orcamento, Item, User, Cliente, Contato

# --- Import do nosso módulo de segurança ---
from security import get_password_hash, verify_password

from pdf_models.modelo_joao import gerar_pdf_joao
from pdf_models.modelo_cacador import gerar_pdf_cacador

PDF_GENERATORS = {
    "joao": gerar_pdf_joao,
    "cacador": gerar_pdf_cacador,
    "default": gerar_pdf_joao 
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

engine = create_engine(DATABASE_URL, connect_args={})

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

# Em app.py

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
    return templates.TemplateResponse("index.html", {"request": request, "user": current_user})

@app.get("/orcamentos", response_class=HTMLResponse)
async def orcamentos_page(request: Request, current_user: User = Depends(get_current_user)):
    admin_username = os.getenv("BASIC_AUTH_USER", "admin")
    return templates.TemplateResponse("orcamentos.html", {"request": request, "user": current_user, "admin_username_from_env": admin_username})


# --- ROTAS DA API ---

@app.post("/salvar-orcamento/")
async def salvar_orcamento_endpoint(
    request: Request,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    form_data = await request.form()
    
    cliente_id_str = form_data.get("cliente_id")
    nome_cliente = form_data.get("nome")
    # verifica se foi marcado para salvar cliente (caso do toggle, se precisar)
    salvar_cliente_flag = form_data.get("salvar_cliente") == "on"
    contatos_json = form_data.get("contatos", "[]") 
    contatos_data = json.loads(contatos_json)

    cliente_db = None
    cliente_id_para_orcamento = None

    # Se usuário selecionou um cliente existente
    if cliente_id_str:
        # Se um cliente existente foi selecionado
        cliente_db = session.get(Cliente, int(cliente_id_str))
        if not cliente_db or cliente_db.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Cliente selecionado inválido.")
        cliente_id_para_orcamento = cliente_db.id

    elif nome_cliente and salvar_cliente_flag:
        cliente_db = Cliente(
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
        session.add(cliente_db)

        session.commit()
        session.refresh(cliente_db)

        cliente_id_para_orcamento = cliente_db.id
    
        for contato_info in contatos_data:
            novo_contato = Contato(
                nome=contato_info.get('nome'),
                telefone=contato_info.get('telefone'),
                 cliente_id=cliente_id_para_orcamento # Linkamos ao cliente
            )
            session.add(novo_contato)

        session.commit()    

    # --- LÓGICA DO ORÇAMENTO (como já estava)
    itens_data = json.loads(form_data.get("itens"))
    total_geral = sum(int(i['quantidade']) * float(i['valor']) for i in itens_data)
    
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
        condicao_pagamento=form_data.get("condicao_pagamento"),
        prazo_entrega=form_data.get("prazo_entrega"),
        garantia=form_data.get("garantia"),
        observacoes=form_data.get("observacoes"),
    )
    session.add(orcamento_db)
    session.commit()
    
    return RedirectResponse(url="/orcamentos", status_code=303)



# ROTA DE API: Lista todos os orçamentos (para o JavaScript)
@app.get("/api/orcamentos/")
def listar_orcamentos_api(
    user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    statement = (
        select(Orcamento)
        .options(selectinload(Orcamento.cliente)) 
        .where(Orcamento.user_id == user.id)
        .order_by(Orcamento.id.desc())
    )
    orcamentos = session.exec(statement).all()
    resultado = []
    for o in orcamentos:
        # Pega o telefone principal, seja do cliente salvo ou do fallback
        telefone_principal = o.cliente.telefone if o.cliente and o.cliente.telefone else o.telefone_cliente
        
        nome_cliente = o.cliente.nome if o.cliente else o.nome_cliente

        resultado.append({
            "id": o.id,
            "numero": o.numero,
            "nome": o.cliente.nome if o.cliente else o.nome_cliente,
            "data_emissao": o.data_emissao,
            "total_geral": o.total_geral,
            "telefone": telefone_principal  # <-- CAMPO NOVO E CRUCIAL
        })
    return resultado



# --- ROTAS DA API PARA ITENS DE CATÁLOGO ---
@app.post("/api/item/", response_model=Item)
def create_item(
    item: Item,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
):
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

    nome_arquivo = f"Orcamento_{orcamento.numero}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'}
    )

@app.get("/orcamento/publico/{token}", response_class=StreamingResponse)
async def get_pdf_publico(token: str, session: Session = Depends(get_db_session)):
    """
    ESTA É A ROTA PÚBLICA QUE O CLIENTE USA. ELA SÓ FUNCIONA COM O TOKEN.
    """
    statement = select(Orcamento).where(Orcamento.token_visualizacao == token)
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Not Found") # Mensagem genérica por segurança

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
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    orcamento = session.get(Orcamento, orcamento_id)
    if not orcamento or orcamento.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")

    # Verifica se o token existe. Se não, avisa para gerar o PDF primeiro.
    if not orcamento.token_visualizacao:
        raise HTTPException(status_code=400, detail="Por favor, clique no ícone de PDF primeiro para gerar o link de compartilhamento.")
        
    # MONTA O LINK PÚBLICO E SEGURO USANDO O TOKEN
    pdf_url = f"{str(request.base_url)}orcamento/publico/{orcamento.token_visualizacao}"
    
    nome_cliente = orcamento.cliente.nome if orcamento.cliente else orcamento.nome_cliente
    mensagem = (
        f"Olá, {nome_cliente}!\n\n"
        f"Segue o seu orçamento de número *{orcamento.numero}*.\n\n"
        f"Visualize o orçamento completo no link abaixo:\n"
        f"{pdf_url}\n\n"
        f"Qualquer dúvida, estou à disposição!"
    )
    
    return JSONResponse(content={"whatsapp_message": quote(mensagem)})

@app.get("/editar-orcamento/{orcamento_id}", response_class=HTMLResponse)
async def editar_orcamento_page(
    orcamento_id: int, 
    request: Request, 
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session) # Usa a sessão da dependência
):
    # USAREMOS selectinload PARA GARANTIR QUE O CLIENTE VENHA JUNTO
    statement = (
        select(Orcamento)
        .options(selectinload(Orcamento.cliente).selectinload(Cliente.contatos)) # A linha mágica
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    )
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    
    # O resto do seu código já estava correto
    return templates.TemplateResponse(
        "editar_orcamento.html", 
        {"request": request, "user": current_user, "orcamento": orcamento}
    )

# SUBSTITUA A FUNÇÃO ATUALIZAR INTEIRA POR ESTA:
@app.post("/atualizar-orcamento/{orcamento_id}")
async def atualizar_orcamento_submit(
    request: Request,
    orcamento_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    form_data = await request.form()
    
    # 1. Busca o orçamento que será atualizado
    orcamento_db = session.exec(select(Orcamento).where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)).first()
    if not orcamento_db:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado para atualizar")

    # 2. ATUALIZA OS DADOS DO CLIENTE ASSOCIADO
    # Acessamos o cliente através da relação orcamento_db.cliente
    cliente_db = orcamento_db.cliente
    if cliente_db:
        cliente_db.nome = form_data.get("nome")
        cliente_db.telefone = form_data.get("telefone")
        cliente_db.cep = form_data.get("cep")
        cliente_db.logradouro = form_data.get("logradouro")
        cliente_db.numero_casa = form_data.get("numero_casa")
        cliente_db.complemento = form_data.get("complemento")
        cliente_db.bairro = form_data.get("bairro")
        cliente_db.cidade_uf = form_data.get("cidade_uf")

        for contato_existente in cliente_db.contatos:
            session.delete(contato_existente)

        contatos_json = form_data.get("contatos", "[]")
        contatos_data = json.loads(contatos_json)
        for contato_info in contatos_data:
            novo_contato = Contato(
                nome=contato_info['nome'], 
                telefone=contato_info['telefone'],
                cliente_id=cliente_db.id
            )
            session.add(novo_contato)

        session.add(cliente_db)    

    # 3. ATUALIZA OS DADOS DO PRÓPRIO ORÇAMENTO
    orcamento_db.numero = form_data.get("numero_orcamento").strip()
    orcamento_db.descricao_servico = form_data.get("descricao_servico")
    
    itens_data = json.loads(form_data.get("itens"))
    orcamento_db.itens = itens_data
    orcamento_db.total_geral = sum(int(i['quantidade']) * float(i['valor']) for i in itens_data)
    
    # 4. Salva tudo e redireciona
    session.commit()
    return RedirectResponse(url="/orcamentos?atualizado=true", status_code=status.HTTP_303_SEE_OTHER)


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

@app.get("/api/proximo-numero/")
def get_proximo_numero(current_user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    # Busca o último orçamento DESTE usuário, ordenando pelo número como inteiro

    ultimo_orcamento = session.exec(
        select(Orcamento)
        .where(Orcamento.user_id == current_user.id)
        .order_by(cast(Orcamento.numero, Integer).desc())
    ).first()
    
    proximo_numero_int = (int(ultimo_orcamento.numero) if ultimo_orcamento else 0) + 1
    return {"proximo_numero": str(proximo_numero_int).zfill(4)}
    
@app.post("/api/resetar-contador/")
async def resetar_contador_endpoint(
    novo_inicio: int = Form(...)
):
    """
    Redefine o contador de orçamentos para um novo valor inicial.
    Se o valor for 0, o próximo orçamento será o 1.
    """
    if novo_inicio < 0:
        raise HTTPException(status_code=400, detail="O número inicial não pode ser negativo.")
    
    file_path = "orcamento_number.txt"
    try:
        # Escreve o novo valor inicial no arquivo.
        # O próximo get_next_orcamento_number() lerá este valor.
        with open(file_path, "w") as f:
            f.write(str(novo_inicio))
        
        return {"message": f"Contador de orçamentos reiniciado com sucesso. O próximo número será {novo_inicio + 1}."}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao resetar o contador: {e}")

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
    id: Optional[int]
    nome: str
    telefone: str

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

# --- ROTAS DA API PARA CLIENTES ---
@app.get("/api/orcamento/{orcamento_id}/contatos", response_model=List[ContatoResponse])
def get_orcamento_contatos(
    orcamento_id: int, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_db_session)
):
    """
    Busca um orçamento pelo ID e retorna a lista de contatos 
    do cliente associado a ele.
    """
    orcamento = session.exec(
        select(Orcamento).options(
            selectinload(Orcamento.cliente).selectinload(Cliente.contatos)
        )
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    ).first()
    
    # Se não encontrar o orçamento ou o cliente, retorna uma lista vazia
    if not orcamento or not orcamento.cliente:
        return []
    
    return orcamento.cliente.contatos

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

@app.post("/orcamento/{orcamento_id}/email/link")
def gerar_link_email(
    orcamento_id: int,
    request: Request,
    destinatario: str = Form(...),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    statement = (
        select(Orcamento)
        .options(selectinload(Orcamento.cliente), selectinload(Orcamento.user))
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    )
    orcamento = session.exec(statement).first()

    if not orcamento:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado")
    
    # Monta o link público e direto, sem tokens.
    pdf_url = f"{str(request.base_url).replace('http://', 'https://')}orcamento/{orcamento_id}/pdf"

    # --- O resto do código continua igual, apenas sem a checagem de token ---
    
    nome_cliente = orcamento.cliente.nome if orcamento.cliente else orcamento.nome_cliente
    assunto = f"Orçamento #{str(orcamento.numero).zfill(4)}"
    
    corpo_email = f"""Olá {nome_cliente},

    Conforme solicitado, segue o seu orçamento de número #{str(orcamento.numero).zfill(4)}.

    Serviço: {orcamento.descricao_servico}

    Você pode visualizar o orçamento completo no link abaixo:
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


 