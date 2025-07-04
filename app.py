
import os
import httpx
import json
import locale
import secrets
import io
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote

# --- Imports do FastAPI e bibliotecas ---
from fastapi import FastAPI, HTTPException, status, Form, Request, Depends, Response, Header
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
from fpdf import FPDF
from sqlmodel import SQLModel, Session, create_engine, select
from contextlib import asynccontextmanager

# --- IMPORTS DO CLOUDINARY (MOVA ELES PARA CÁ) ---
import cloudinary
import cloudinary.uploader
import cloudinary.api

# --- Import dos seus modelos de dados ---
from models import Orcamento, Item, User

# --- Import do nosso módulo de segurança ---
from security import get_password_hash, verify_password

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

# --- FUNÇÕES AUXILIARES ---
def get_next_orcamento_number():
    file_path = "orcamento_number.txt"
    try:
        with open(file_path, "r") as f:
            current = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        current = 0
    next_number = current + 1
    with open(file_path, "w") as f:
        f.write(str(next_number))
    return str(next_number).zfill(4)

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

class MyPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client_data = {}
        self.orcamento_data = {}
        self.set_auto_page_break(auto=True, margin=15)

    def set_all_data(self, client_data, orcamento_data):
        self.client_data = client_data
        self.orcamento_data = orcamento_data

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=145, y=5, w=60)
        self.set_xy(0, 50)
        self.set_font("Arial", "B", 24)
        self.set_text_color(0, 51, 102)
        self.cell(self.w, 10, "ORÇAMENTO", align='C', ln=True)
        self.set_xy(0, self.get_y() - 2)
        self.set_font("Arial", "B", 18)
        self.cell(self.w, 8, f"Nº{self.orcamento_data.get('numero_orcamento', '')}", align='C', ln=True)
        self.ln(-2)
        self.set_font("Arial", "", 6)
        self.set_text_color(0, 51, 102)
        self.set_x(10)
        self.cell(0, 4, f"DATA EMISSÃO: {self.orcamento_data.get('data_emissao', '')}", align='L', ln=True)
        self.ln(2)

    def footer(self):
        pass

    def draw_content(self, orcamento: Orcamento):
        # Esta função centraliza a lógica de desenho do conteúdo do PDF
        campos = [("CLIENTE: ", orcamento.nome),("ENDEREÇO: ", orcamento.endereco),("TELEFONE: ", orcamento.telefone),("DESCRIÇÃO DO SERVIÇO: ", orcamento.descricao_servico)]
        current_y = 70
        for label, value in campos:
            is_desc = label.startswith("DESCRIÇÃO")
            self.set_font("Arial", "B", 10)
            w_label = self.get_string_width(label)
            w_val = TABLE_TOTAL_WIDTH - w_label - 2 * PADDING_RECT_VERTICAL
            if not is_desc:
                h_rect = FIXED_RECT_HEIGHT
            else:
                self.set_font("Arial", "", 10)
                lines = self.multi_cell(w_val, LINE_HEIGHT, value, split_only=True)
                h_rect = max(FIXED_RECT_HEIGHT, len(lines) * LINE_HEIGHT + 2 * PADDING_RECT_VERTICAL)
            
            self.set_fill_color(240, 240, 240)
            self.rect(10, current_y, TABLE_TOTAL_WIDTH, h_rect, "F")
            self.set_xy(10 + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
            self.set_font("Arial", "B", 10)
            self.set_text_color(0, 51, 102)
            self.cell(w_label, LINE_HEIGHT, label, ln=0)
            self.set_text_color(0, 0, 0)
            self.set_font("Arial", "", 10)
            self.set_xy(10 + w_label + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
            self.multi_cell(w_val, LINE_HEIGHT, value)
            current_y += h_rect + 2
        
        self.set_y(current_y)
        self.ln(2)

        servicos = [i for i in orcamento.itens if i["tipo"].lower() == "servico"]
        materiais = [i for i in orcamento.itens if i["tipo"].lower() == "material"]

        if servicos:
            self.ln(4)
            self.set_font("Arial", "B", 12)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Serviços", ln=True, align="L")
            self.draw_table(servicos)

        if materiais:
            self.ln(4)
            self.set_font("Arial", "B", 12)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Materiais", ln=True, align="L")
            self.draw_table(materiais)

        self.ln(4)
        self.set_font("Arial", "B", 10)
        self.set_fill_color(255, 204, 0)
        self.set_text_color(0, 51, 102)
        label_w = sum(TABLE_COL_WIDTHS[:-1])
        self.set_x(10)
        self.cell(label_w, 8, "TOTAL GERAL:", 0, align='R', fill=True)
        self.cell(TABLE_COL_WIDTHS[-1], 8, format_brl(orcamento.total_geral), 0, align="R", fill=True)
        self.set_y(-30)
        self.set_font("Arial", "B", 10)
        self.set_text_color(0, 51, 102)
        self.cell(0, 7, "VALIDADE DO DOCUMENTO:", ln=True)
        self.set_font("Arial", "B", 10)
        self.cell(0, 7, orcamento.data_validade, ln=True)

    def draw_table(self, itens_do_tipo):
        titles = ["ITEM", "DESCRIÇÃO", "QTD", "UNITÁRIO", "TOTAL"]
        self.set_fill_color(255, 204, 0)
        self.set_font("Arial", "B", 9)
        self.set_text_color(0, 51, 102)
        self.set_x(10)
        for w, title in zip(TABLE_COL_WIDTHS, titles):
            self.cell(w, 8, title, 1, align='C', fill=True)
        self.ln()

        for idx, it in enumerate(itens_do_tipo, start=1):
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            start_y = self.get_y()
            lines = self.multi_cell(TABLE_COL_WIDTHS[1], 5, it["desc"], split_only=True)
            text_height = len(lines) * 5
            row_height = max(10, text_height + 4)
            if start_y + row_height > self.page_break_trigger:
                self.add_page()
                self.draw_header()
                start_y = self.get_y()
            
            self.set_y(start_y)
            self.set_x(10)
            self.cell(TABLE_COL_WIDTHS[0], row_height, str(idx), border=1, align='C')
            x_after_item = self.get_x()
            y_text_pos = start_y + (row_height - text_height) / 2
            self.set_xy(x_after_item, y_text_pos)
            self.multi_cell(TABLE_COL_WIDTHS[1], 5, it["desc"], border=0, align='L')
            self.rect(x=x_after_item, y=start_y, w=TABLE_COL_WIDTHS[1], h=row_height)
            self.set_y(start_y)
            self.set_x(x_after_item + TABLE_COL_WIDTHS[1])
            self.cell(TABLE_COL_WIDTHS[2], row_height, str(it["qtd"]), border=1, align='C')
            self.cell(TABLE_COL_WIDTHS[3], row_height, format_brl(it['unit']), border=1, align="C")
            self.cell(TABLE_COL_WIDTHS[4], row_height, format_brl(it['total']), border=1, align="C", ln=1)

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
        admin_user = User(username=admin_username, hashed_password=hashed_password)
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
    current_user: User = Depends(get_current_user),
    nome: str = Form(...),
    logradouro: str = Form(...),
    numero_casa: str = Form(...),
    complemento: str = Form(""),
    bairro: str = Form(...),
    cidade_uf: str = Form(...),
    cep: str = Form(...),
    telefone: str = Form(...),
    descricao_servico: str = Form(...),
    itens: str = Form(...),
    numero_orcamento: str = Form(...)
):
    # 1. Define o número final do orçamento
    numero_final = numero_orcamento.strip()
    if not numero_final:
        numero_final = get_next_orcamento_number()
    else:
        try:
            with open("orcamento_number.txt", "r") as f:
                contador_atual = int(f.read().strip())
            proximo_no_contador = max(int(numero_final), contador_atual)
            with open("orcamento_number.txt", "w") as f:
                f.write(str(proximo_no_contador))
        except (FileNotFoundError, ValueError):
            with open("orcamento_number.txt", "w") as f:
                f.write(numero_final)
    
    # 2. Processa todos os dados recebidos do formulário
    itens_data = json.loads(itens)
    partes_endereco = [f"{logradouro}, Nº {numero_casa}", complemento.strip(), bairro]
    endereco_formatado = f"{', '.join(filter(None, partes_endereco))} - {cidade_uf} - CEP {cep}"
    itens_formatados = [{"id": i.get('id'), "tipo": i['tipo'], "desc": i['nome'], "qtd": int(i['quantidade']), "unit": float(i['valor']), "total": int(i['quantidade']) * float(i['valor'])} for i in itens_data]
    total_geral = sum(i["total"] for i in itens_formatados)
    hoje = datetime.now()
    data_emissao = hoje.strftime('%d/%m/%Y')
    data_validade = (hoje + timedelta(days=7)).strftime('%d/%m/%Y')

    # 3. Cria e salva o objeto no banco de dados, AGORA que todas as variáveis existem
    with Session(engine) as session:
        orcamento_db = Orcamento(
            numero=numero_final,
            nome=nome,
            endereco=endereco_formatado,
            telefone=telefone,
            descricao_servico=descricao_servico,
            itens=itens_formatados,
            total_geral=total_geral,
            data_emissao=data_emissao,
            data_validade=data_validade,
            user_id=current_user.id  # Associação com o usuário logado
        )
        session.add(orcamento_db)
        session.commit()
    
    return RedirectResponse(url="/orcamentos", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/orcamento/{orcamento_id}/pdf", response_class=StreamingResponse)
async def gerar_e_salvar_pdf(orcamento_id: int, current_user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    with Session(engine) as session:
        orcamento = session.get(Orcamento, orcamento_id)
        if not orcamento:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        
        if orcamento.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Acesso negado")

        # Verifica se o PDF já foi gerado e salvo antes
        if orcamento.pdf_url:
            print(f"PDF já existe na nuvem. Buscando de: {orcamento.pdf_url}")
           
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(orcamento.pdf_url) 
                    response.raise_for_status()

                pdf_bytes = response.content

                return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Orcamento_{orcamento.numero}.pdf"'})

            except Exception as e:
                print(f"Falha ao buscar PDF do Cloudinary, gerando novamente... Erro: {e}")    

        # --- SE O PDF AINDA NÃO EXISTE, GERAMOS E FAZEMOS O UPLOAD ---
        print(f"Gerando novo PDF para o orçamento #{orcamento.id}")
        
        # 1. Gera o PDF em memória (seu código existente)
        pdf = MyPDF(format="A4")
        pdf.set_all_data(
            client_data={"nome": orcamento.nome, "endereco": orcamento.endereco, "telefone": orcamento.telefone},
            orcamento_data={"numero_orcamento": orcamento.numero, "data_emissao": orcamento.data_emissao}
        )
        pdf.add_page()
        pdf.draw_content(orcamento)
        
        pdf_bytes = pdf.output(dest="S").encode("latin1")
        
        # 2. Faz o upload dos bytes do PDF para o Cloudinary
        try:
            upload_result = cloudinary.uploader.upload(
                file=pdf_bytes,
                folder="orcamentos_pdf",  # Organiza os PDFs em uma pasta
                public_id=f"Orcamento_{orcamento.numero}", # Nome do arquivo na nuvem
                resource_type="raw", # Usamos 'raw' para arquivos não-imagem como PDF
                flags="attachment:inline"
            )
            
            # 3. Pega a URL segura do arquivo na nuvem
            secure_url = upload_result.get("secure_url")
            if not secure_url:
                raise Exception("Cloudinary não retornou uma URL segura.")

            # 4. Salva a URL no banco de dados para uso futuro
            orcamento.pdf_url = secure_url
            session.add(orcamento)
            session.commit()
            print(f"PDF salvo na nuvem com sucesso. URL: {secure_url}")

        except Exception as e:
            print(f"Erro no upload para Cloudinary: {e}")
            raise HTTPException(status_code=500, detail="Falha ao fazer upload do PDF.")
        
        # 5. Envia o PDF para o navegador do usuário, como antes
        return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="Orcamento_{orcamento.numero}.pdf"'})

# ROTA DE API: Lista todos os orçamentos (para o JavaScript)
@app.get("/api/orcamentos/", response_model=List[Orcamento])
def listar_orcamentos_api(user: User = Depends(get_current_user)):
    with Session(engine) as session:
        statement = select(Orcamento).where(Orcamento.user_id == user.id).order_by(Orcamento.id.desc())
        orcamentos = session.exec(statement).all()
        return orcamentos


# --- ROTAS DA API PARA ITENS DE CATÁLOGO ---
@app.post("/api/item/", response_model=Item)
def create_item(item: Item):
    with Session(engine) as session:
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

@app.get("/api/servico/", response_model=List[Item])
def read_servicos():
    with Session(engine) as session:
        statement = select(Item).where(Item.tipo == "servico")
        return session.exec(statement).all()

@app.get("/api/materiais/", response_model=List[Item])
def read_materiais():
    with Session(engine) as session:
        statement = select(Item).where(Item.tipo == "material")
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
@app.get("/orcamento/{orcamento_id}/whatsapp")
def gerar_link_whatsapp(orcamento_id: int, request: Request, current_user: User = Depends(get_current_user), session: Session = Depends(get_db_session)):
    with Session(engine) as session:
        orcamento = session.get(Orcamento, orcamento_id)
        if not orcamento:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        
        if orcamento.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Acesso negado")

    pdf_url = f"{str(request.base_url)}orcamento/{orcamento.id}/pdf"

    # Formatar a mensagem para o WhatsApp
    mensagem = (
        f"Olá, {orcamento.nome}!\n\n"
        f"Segue o seu orçamento de número *{orcamento.numero}*.\n\n"
        f"*{orcamento.descricao_servico}*\n\n"
        f"Valor Total: *{format_brl(orcamento.total_geral)}*\n"
        f"Validade: {orcamento.data_validade}\n\n"
        f"Visualize o orçamento em PDF:\n\n"
        f"{pdf_url}\n\n"
        f"Qualquer dúvida, estou à disposição!"
    )
    # Codifica a mensagem para ser usada em uma URL
    mensagem_codificada = quote(mensagem)
    # Remove parênteses, espaços, hífens, etc.
    telefone_limpo = ''.join(filter(str.isdigit, orcamento.telefone))
    # Adiciona o código do país (55 para o Brasil) se não tiver
    if not telefone_limpo.startswith("55"):
        telefone_limpo = "55" + telefone_limpo

    whatsapp_url = f"https://wa.me/{telefone_limpo}?text={mensagem_codificada}"

    return JSONResponse(content={"whatsapp_url":whatsapp_url})

@app.get("/editar-orcamento/{orcamento_id}", response_class=HTMLResponse)
async def editar_orcamento_page(
    orcamento_id: int, 
    request: Request, 
    current_user: User = Depends(get_current_user) # Nome padronizado para 'current_user'
):
    with Session(engine) as session:
        orcamento = session.get(Orcamento, orcamento_id)
        if not orcamento:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado")
        
        # Agora a verificação de permissão funciona
        if orcamento.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado")
    
    # E passamos a variável correta para o template
    return templates.TemplateResponse(
        "editar_orcamento.html", 
        {"request": request, "user": current_user, "orcamento": orcamento}
    )

# SUBSTITUA SUA FUNÇÃO DE ATUALIZAÇÃO INTEIRA POR ESTA

@app.post("/atualizar-orcamento/{orcamento_id}")
async def atualizar_orcamento_submit(
    orcamento_id: int,
    numero_orcamento: str = Form(...),
    nome: str = Form(...),
    logradouro: str = Form(...),
    numero_casa: str = Form(...),
    complemento: str = Form(""),
    bairro: str = Form(...),
    cidade_uf: str = Form(...),
    cep: str = Form(...),
    telefone: str = Form(...),
    descricao_servico: str = Form(...),
    itens: str = Form(...),
    current_user: User = Depends(get_current_user)
):
    with Session(engine) as session:
        # 1. Busca o orçamento que será atualizado, UMA ÚNICA VEZ.
        orcamento_db = session.exec(select(Orcamento).where(Orcamento.id == orcamento_id, Orcamento.user_id == current_user.id)).first()
        if not orcamento_db:
            raise HTTPException(status_code=404, detail="Orçamento não encontrado para atualizar")

        # 2. Atualiza todos os campos do objeto com os dados do formulário.
        orcamento_db.numero = numero_orcamento.strip()
        orcamento_db.nome = nome
        partes_endereco = [f"{logradouro}, Nº {numero_casa}", complemento.strip(), bairro]
        orcamento_db.endereco = f"{', '.join(filter(None, partes_endereco))} - {cidade_uf} - CEP {cep}"
        orcamento_db.telefone = telefone
        orcamento_db.descricao_servico = descricao_servico
        
        itens_data = json.loads(itens)
        
        # 3. Converte os itens do JavaScript para o formato do banco de dados.
        itens_formatados_para_db = []
        for item_js in itens_data:
            itens_formatados_para_db.append({
                "id": item_js.get('id'),
                "tipo": item_js['tipo'],
                "desc": item_js['nome'],      # Converte 'nome' para 'desc'
                "qtd": int(item_js['quantidade']),
                "unit": float(item_js['valor']),
                "total": int(item_js['quantidade']) * float(item_js['valor'])
            })
        
        orcamento_db.itens = itens_formatados_para_db
        orcamento_db.total_geral = sum(i["total"] for i in itens_formatados_para_db)

        # 4. Atualiza a data de emissão para a data da modificação
        orcamento_db.data_emissao = datetime.now().strftime('%d/%m/%Y')
        orcamento_db.data_validade = (datetime.now() + timedelta(days=7)).strftime('%d/%m/%Y')
        
        # 5. Salva o objeto modificado no banco de dados.
        session.add(orcamento_db)
        session.commit()

    # 6. Redireciona o usuário para a lista de orçamentos com uma mensagem de sucesso.
    return RedirectResponse(url="/orcamentos?atualizado=true", status_code=status.HTTP_303_SEE_OTHER)

# Em app.py

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
def sugerir_proximo_numero():
    file_path = "orcamento_number.txt"
    try:
        with open(file_path, "r") as f:
            current = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        current = 0
    
    # Apenas sugere, não incrementa o arquivo aqui
    next_number = current + 1
    return {"proximo_numero": str(next_number).zfill(4)}

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
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user) # Garante que só um usuário logado pode criar outros
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
    new_user = User(username=username, hashed_password=hashed_password)

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

 