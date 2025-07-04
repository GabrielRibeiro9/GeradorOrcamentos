
from typing import Optional, List
from sqlmodel import Field, SQLModel, JSON, Column, Relationship

# O modelo Item permanece o mesmo
class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo: str
    nome: str
    valor: float

# Forward reference para User, para evitar erro de importação circular
class Orcamento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    numero: str
    nome: str
    endereco: str
    telefone: str
    descricao_servico: str
    itens: List[dict] = Field(sa_column=Column(JSON))
    total_geral: float
    data_emissao: str
    data_validade: str
    pdf_url: Optional[str] = Field(default=None)

    # --- MUDANÇA AQUI: Chave Estrangeira que liga ao Usuário ---
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    
    # --- MUDANÇA AQUI: Relação que permite acessar o usuário a partir do orçamento ---
    user: Optional["User"] = Relationship(back_populates="orcamentos")


# NOVO MODELO: User
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str # Armazenará a senha criptografada
    
    # --- MUDANÇA AQUI: Relação que permite acessar os orçamentos a partir do usuário ---
    orcamentos: List[Orcamento] = Relationship(back_populates="user")