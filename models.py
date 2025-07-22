from typing import Optional, List
from sqlmodel import Field, SQLModel, JSON, Column, Relationship

# --- Modelo Item (Sem alterações) ---
class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tipo: str
    nome: str
    valor: float
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="itens")


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    hashed_password: str
    
    # --- ADICIONE ESTE NOVO CAMPO ---
    pdf_template_name: str = Field(default="default")
    
    # --- Relacionamentos existentes (não mude) ---
    itens: List["Item"] = Relationship(back_populates="user")
    clientes: List["Cliente"] = Relationship(back_populates="user")
    orcamentos: List["Orcamento"] = Relationship(back_populates="user")     

# --- Modelo Cliente ---

class Cliente(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    telefone: Optional[str] = Field(default=None)
    cep: str
    logradouro: str
    numero_casa: str
    complemento: Optional[str] = Field(default=None)
    bairro: str
    cidade_uf: str
    user_id: int = Field(foreign_key="user.id")
    user: "User" = Relationship(back_populates="clientes")
    
    orcamentos: List["Orcamento"] = Relationship(back_populates="cliente")

    contatos: List["Contato"] = Relationship(back_populates="cliente", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

# --- Modelo Orcamento (Atualizado) ---
class Orcamento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    numero: str
    descricao_servico: str
    itens: List[dict] = Field(sa_column=Column(JSON))
    total_geral: float
    data_emissao: str
    data_validade: str
    pdf_url: Optional[str] = Field(default=None)
    token_visualizacao: Optional[str] = Field(default=None, index=True) 
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    nome_cliente: Optional[str] = None
    telefone_cliente: Optional[str] = None
    cep_cliente: Optional[str] = None
    logradouro_cliente: Optional[str] = None
    numero_casa_cliente: Optional[str] = None
    complemento_cliente: Optional[str] = None
    bairro_cliente: Optional[str] = None
    cidade_uf_cliente: Optional[str] = None
    condicao_pagamento: Optional[str] = Field(default=None)
    prazo_entrega: Optional[str] = Field(default=None)
    garantia: Optional[str] = Field(default=None)
    observacoes: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default="Orçamento", index=True)
    
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    user: Optional["User"] = Relationship(back_populates="orcamentos")

    # Esta é a chave estrangeira que conecta ao cliente
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    cliente: Optional[Cliente] = Relationship(back_populates="orcamentos")

class Contato(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str = Field(index=True)
    telefone: str
    
    # Chave estrangeira para ligar o contato ao cliente.
    cliente_id: Optional[int] = Field(default=None, foreign_key="cliente.id")
    
    # A Relação que permite, a partir de um Contato,
    # saber a qual Cliente ele pertence.
    cliente: Optional["Cliente"] = Relationship(back_populates="contatos")


 