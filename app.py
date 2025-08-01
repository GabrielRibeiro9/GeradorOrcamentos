
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
from models import Orcamento, Item, User, Cliente, Contato, ContatoOrcamento

# --- Import do nosso módulo de segurança ---
from security import get_password_hash, verify_password

from pdf_models.modelo_joao import gerar_pdf_joao
from pdf_models.modelo_cacador import gerar_pdf_cacador
from pdf_models.modelo_apresentacao import gerar_pdf_apresentacao

PDF_GENERATORS = {
    "joao": gerar_pdf_joao,
    "cacador": gerar_pdf_cacador,
    "apresentacao": gerar_pdf_apresentacao,
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
    current_user: User = Depends(get_current_user)
):
    form_data = await request.form()
    
    cliente_id_str = form_data.get("cliente_id")
    nome_cliente = form_data.get("nome")
    # verifica se foi marcado para salvar cliente (caso do toggle, se precisar)
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
    
    orcamento_db = session.exec(
        select(Orcamento).options(selectinload(Orcamento.contatos_extras)) # Carrega os contatos antigos do ORÇAMENTO
        .where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)
    ).first()
    if not orcamento_db:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado para atualizar")

    # ATUALIZA OS DADOS DE FALLBACK (copiados para o orçamento)
    orcamento_db.nome_cliente = form_data.get("nome")
    orcamento_db.telefone_cliente = form_data.get("telefone")
    orcamento_db.cep_cliente = form_data.get("cep")
    orcamento_db.logradouro_cliente = form_data.get("logradouro")
    orcamento_db.numero_casa_cliente = form_data.get("numero_casa")
    orcamento_db.complemento_cliente = form_data.get("complemento")
    orcamento_db.bairro_cliente = form_data.get("bairro")
    orcamento_db.cidade_uf_cliente = form_data.get("cidade_uf")

    if orcamento_db.cliente:
        cliente = orcamento_db.cliente  # Pega o objeto do cliente relacionado
        cliente.nome = form_data.get("nome")
        cliente.telefone = form_data.get("telefone")
        cliente.cep = form_data.get("cep")
        cliente.logradouro = form_data.get("logradouro")
        cliente.numero_casa = form_data.get("numero_casa")
        cliente.complemento = form_data.get("complemento")
        cliente.bairro = form_data.get("bairro")
        cliente.cidade_uf = form_data.get("cidade_uf")

        # Também sincroniza os contatos extras para o registro do cliente
        # Primeiro, remove os contatos antigos do cliente
        cliente.contatos.clear()
        
        # Depois, adiciona os novos contatos (vindos do formulário) ao cliente
        contatos_json = form_data.get("contatos", "[]")
        contatos_data = json.loads(contatos_json)
        for contato_info in contatos_data:
            cliente.contatos.append(
                Contato(
                    nome=contato_info['nome'], 
                    telefone=contato_info['telefone'],
                    email=contato_info.get('email')
                )
            )
        
        session.add(cliente)
    
    # ATUALIZA OS DADOS DO ORÇAMENTO
    orcamento_db.numero = form_data.get("numero_orcamento").strip()
    orcamento_db.descricao_servico = form_data.get("descricao_servico")
    
    itens_data = json.loads(form_data.get("itens"))
    orcamento_db.itens = itens_data
    orcamento_db.total_geral = sum(int(i.get('quantidade', 0)) * float(i.get('valor', 0)) for i in itens_data)
    
    orcamento_db.condicao_pagamento = form_data.get("condicao_pagamento")
    orcamento_db.prazo_entrega = form_data.get("prazo_entrega")
    orcamento_db.garantia = form_data.get("garantia")
    orcamento_db.observacoes = form_data.get("observacoes")

    # ATUALIZA A LISTA DE CONTATOS DO ORÇAMENTO
    orcamento_db.contatos_extras.clear()
    contatos_json = form_data.get("contatos", "[]")
    contatos_data = json.loads(contatos_json)
    for contato_info in contatos_data:
        orcamento_db.contatos_extras.append(
            ContatoOrcamento(
                nome=contato_info['nome'], 
                telefone=contato_info['telefone'],
                email=contato_info.get('email')
            )
        )
    
    session.add(orcamento_db)
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