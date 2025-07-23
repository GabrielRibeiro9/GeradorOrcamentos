# Usa imagem oficial do Python
FROM python:3.12-slim

# Define diretório de trabalho no container
WORKDIR /app

# Copia dependências e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante dos arquivos do projeto
COPY . .

# Expõe a porta 8080 (Fly.io exige)
EXPOSE 8000

# Comando para rodar FastAPI com Uvicorn na porta 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
