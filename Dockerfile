# Dockerfile para ejecutar análisis de datos en Python
# Usa una imagen base de Python liviana y segura
FROM python:3.9-slim-buster

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia los archivos de requisitos y los instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todos los demás archivos de tu proyecto al contenedor
COPY . .

# Streamlit necesita saber en qué puerto escuchar.
EXPOSE 8080

# Comando para ejecutar tu app de Streamlit en el puerto 8080 y desactivar CORS/XSRF
# ¡IMPORTANTE! Agregado: "--server.address", "0.0.0.0"
CMD ["streamlit", "run", "Analisis Financiero.py", "--server.port", "8080", "--server.address", "0.0.0.0", "--server.enableCORS", "false", "--server.enableXsrfProtection", "false"]
