import os
import httpx
import json
import locale
import secrets
import io
from datetime import datetime, timedelta
from fastapi import Path, FastAPI, HTTPException, status, Form, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fpdf import FPDF
from sqlmodel import Field, SQLModel, Session, create_engine, select
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.templating import Jinja2Templates

load_dotenv( )

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado")
    return user


try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, ('pt_BR', 'UTF-8'))
    except locale.Error:
        print("Aviso: Localidade 'pt_BR.UTF-8' não encontrada.")
       

USERNAME = os.getenv("BASIC_AUTH_USER", "admin")
PASSWORD = os.getenv("BASIC_AUTH_PASS", "secret")


BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

FULL_PAGE_BACKGROUND_IMAGE = os.path.join(STATIC_DIR, 'full_page_background.png')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo.png')

FIXED_RECT_HEIGHT = 10
PADDING_RECT_VERTICAL = 1
LINE_HEIGHT = 5
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

app = FastAPI(
    title="Orçamento API",

)
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "sua_chave_aqui")) 
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class Item(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    tipo: str
    nome: str
    quantidade: int
    valor: float

sqlite_file = "database.db"
engine = create_engine(f"sqlite:///{sqlite_file}")
SQLModel.metadata.create_all(engine)

def get_next_orcamento_number():
    file_path = "orcamento_number.txt"
    current = 1
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            try:
                current = int(f.read().strip())
            except (ValueError, IndexError):
                current = 1
    next_number = current + 1
    with open(file_path, "w") as f:
        f.write(str(next_number))
    return str(current).zfill(4)

@app.post("/gerar-pdf/")
async def gerar_pdf(
    nome: str = Form(...),
    logradouro: str = Form(...),
    numero_casa: str = Form(...),
    complemento: str = Form(""),
    bairro: str = Form(...),
    cidade_uf: str = Form(...),
    cep: str = Form(...),
    telefone: str = Form(...),
    descricao_servico: str = Form(...),
    itens: str = Form(...)
):
    try:
        itens_data = json.loads(itens)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Formato de 'itens' inválido.")

    partes_endereco = [f"{logradouro}, Nº {numero_casa}"]
    if complemento.strip():
        partes_endereco.append(complemento.strip())
    partes_endereco.append(bairro)
    endereco_formatado = f"{', '.join(partes_endereco)} - {cidade_uf} - CEP {cep}"

    itens_pdf = []
    for item in itens_data:
        try:
            total = int(item['quantidade']) * float(item['valor'])
            itens_pdf.append({
                "tipo": item['tipo'],"desc": item['nome'],"qtd": int(item['quantidade']),
                "unit": float(item['valor']),"total": total
            })
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=f"Item inválido na lista: {item}. Erro: {e}")

    total_geral = sum(i["total"] for i in itens_pdf)
    numero = get_next_orcamento_number()
    hoje = datetime.now()
    data_emissao = hoje.strftime('%d/%m/%Y')
    data_validade = (hoje + timedelta(days=7)).strftime('%d/%m/%Y')

    pdf = MyPDF(format="A4")
    pdf.set_all_data(
        client_data={"nome": nome, "endereco": endereco_formatado, "telefone": telefone},
        orcamento_data={"numero_orcamento": numero, "data_emissao": data_emissao}
    )
    pdf.add_page()
    
    campos = [("CLIENTE: ", nome),("ENDEREÇO: ", endereco_formatado),("TELEFONE: ", telefone),("DESCRIÇÃO DO SERVIÇO: ", descricao_servico)]
    current_y = 70
    for label, value in campos:
        is_desc = label.startswith("DESCRIÇÃO")
        pdf.set_font("Arial", "B", 10)
        w_label = pdf.get_string_width(label)
        w_val = TABLE_TOTAL_WIDTH - w_label - 2 * PADDING_RECT_VERTICAL
        if not is_desc:
            h_rect = FIXED_RECT_HEIGHT
        else:
            pdf.set_font("Arial", "", 10)
            lines = pdf.multi_cell(w_val, LINE_HEIGHT, value, split_only=True)
            h_rect = max(FIXED_RECT_HEIGHT, len(lines) * LINE_HEIGHT + 2 * PADDING_RECT_VERTICAL)
        pdf.set_fill_color(240, 240, 240)
        pdf.rect(10, current_y, TABLE_COL_WIDTHS[0] + TABLE_COL_WIDTHS[1] + TABLE_COL_WIDTHS[2] + TABLE_COL_WIDTHS[3] + TABLE_COL_WIDTHS[4], h_rect, "F")
        pdf.set_xy(10 + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(0, 51, 102)
        pdf.cell(w_label, LINE_HEIGHT, label, ln=0)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 10)
        pdf.set_xy(10 + w_label + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
        pdf.multi_cell(w_val, LINE_HEIGHT, value)
        current_y += h_rect + 2
    pdf.set_y(current_y)
    pdf.ln(2)

    def draw_header():
        titles = ["ITEM", "DESCRIÇÃO", "QTD", "UNITÁRIO", "TOTAL"]
        pdf.set_fill_color(255, 204, 0)
        pdf.set_font("Arial", "B", 9)
        pdf.set_text_color(0, 51, 102)
        pdf.set_x(10)
        for w, title in zip(TABLE_COL_WIDTHS, titles):
            pdf.cell(w, 8, title, 1, align='C', fill=True)
        pdf.ln()

    def draw_row(n, it):
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(0, 0, 0)
        start_y = pdf.get_y()
        lines = pdf.multi_cell(TABLE_COL_WIDTHS[1], 5, it["desc"], split_only=True)
        text_height = len(lines) * 5
        row_height = max(10, text_height + 4)
        if start_y + row_height > pdf.page_break_trigger:
            pdf.add_page()
            draw_header()
            start_y = pdf.get_y()
        pdf.set_y(start_y)
        pdf.set_x(10)
        pdf.cell(TABLE_COL_WIDTHS[0], row_height, str(n), border=1, align='C')
        x_after_item = pdf.get_x()
        y_text_pos = start_y + (row_height - text_height) / 2
        pdf.set_xy(x_after_item, y_text_pos)
        pdf.multi_cell(TABLE_COL_WIDTHS[1], 5, it["desc"], border=0, align='L')
        pdf.rect(x=x_after_item, y=start_y, w=TABLE_COL_WIDTHS[1], h=row_height)
        pdf.set_y(start_y)
        pdf.set_x(x_after_item + TABLE_COL_WIDTHS[1])
        pdf.cell(TABLE_COL_WIDTHS[2], row_height, str(it["qtd"]), border=1, align='C')
        pdf.cell(TABLE_COL_WIDTHS[3], row_height, locale.currency(it['unit'], grouping=True), border=1, align="C")
        pdf.cell(TABLE_COL_WIDTHS[4], row_height, locale.currency(it['total'], grouping=True), border=1, align="C", ln=1)

    servicos = [i for i in itens_pdf if i["tipo"].lower() == "servico"]
    materiais = [i for i in itens_pdf if i["tipo"].lower() == "material"]
    if servicos:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 51, 102)
        pdf.cell(0, 10, "Serviços", ln=True, align="L")
        draw_header()
        for idx, obj in enumerate(servicos, start=1):
            draw_row(idx, obj)
    if materiais:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 51, 102)
        pdf.cell(0, 10, "Materiais", ln=True, align="L")
        draw_header()
        for idx, obj in enumerate(materiais, start=1):
            draw_row(idx, obj)
    pdf.ln(4)
    pdf.set_font("Arial", "B", 10)
    pdf.set_fill_color(255, 204, 0)
    pdf.set_text_color(0, 51, 102)
    label_w = sum(TABLE_COL_WIDTHS[:-1])
    pdf.set_x(10)
    pdf.cell(label_w, 8, "TOTAL GERAL:", 0, align='R', fill=True)
    pdf.cell(TABLE_COL_WIDTHS[-1], 8, locale.currency(total_geral, grouping=True), 0, align="R", fill=True)
    pdf.set_y(-30)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 7, "VALIDADE DO DOCUMENTO:", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(0, 7, data_validade, ln=True)

    file_name = f"Orcamento_{nome.strip().replace(' ', '_')}_{numero}.pdf"
    file_path = os.path.join(STATIC_DIR, file_name)
    pdf.output(file_path)

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Orçamento Gerado</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                font-family: Arial, sans-serif;
                background: #f9fafb;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            .pdf-actions {{
                margin: 16px 0;
                display: flex;
                flex-direction: row;
                gap: 12px;
            }}
            .pdf-actions a {{
                display: inline-block;
                background: #059669;
                color: #fff;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
                text-decoration: none;
                transition: background 0.2s;
            }}
            .pdf-actions a:hover {{
                background: #047857;
            }}
            @media (max-width: 600px) {{
                iframe {{
                    width: 100vw;
                    height: 65vh;
                }}
            }}
            @media (min-width: 601px) {{
                iframe {{
                    width: 90vw;
                    height: 75vh;
                }}
            }}
        </style>
    </head>
    <body>
        <h1 style="color:#059669;margin-top:1rem;">Orçamento Gerado</h1>
        <div class="pdf-actions">
            <a href="/static/{file_name}" download>📥 Baixar PDF</a>
            <a href="/static/{file_name}" target="_blank">🔗 Abrir em nova aba</a>
        </div>
        <iframe src="/static/{file_name}" frameborder="0"></iframe>
    </body>
    </html>
    """)


@app.post("/api/item/", response_model=Item)
def create_item(item: Item):
    with Session(engine) as session:
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

@app.get("/api/servico/", response_model=list[Item])
def read_servicos():
    with Session(engine) as session:
        statement = select(Item).where(Item.tipo == "servico")
        return session.exec(statement).all()

@app.get("/api/materiais/", response_model=list[Item])
def read_materiais():
    with Session(engine) as session:
        statement = select(Item).where(Item.tipo == "material")
        return session.exec(statement).all()

@app.get("/api/item/", response_model=list[Item])
def read_all_items():
    with Session(engine) as session:
        statement = select(Item)
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

@app.get("/api/cep/{cep}", tags=["CEP"])
async def consulta_cep(
    cep: str = Path(..., pattern=r"^\d{5}-?\d{3}$", examples=["01310-200"])
):
    url = f"https://viacep.com.br/ws/{cep.replace('-', '' )}/json/"
    async with httpx.AsyncClient( ) as cliente:
        resp = await cliente.get(url, timeout=5)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Erro ao consultar ViaCEP")
    data = resp.json()
    if data.get("erro"):
        raise HTTPException(status_code=404, detail="CEP não encontrado")
    return data


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if secrets.compare_digest(username, USERNAME) and secrets.compare_digest(password, PASSWORD):
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login?error=true", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open("templates/login.html", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()  # Remove todos os dados da sessão
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@app.exception_handler(StarletteHTTPException)
async def auth_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse("/login")
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    username = request.session.get("user")
    if not username:
        # Não autenticado, redireciona para login
        return RedirectResponse(url="/login")
    # Usuário autenticado, renderiza o formulário normalmente
    return templates.TemplateResponse("index.html", {"request": request, "user": username})

