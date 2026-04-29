# PythIA - Aplicaicón final

Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentra la versión final de la aplicaicón. Esta preparada para ejecutarse desde cualquier dispositivo sin la necesidad de gestionar sus dependencias, ya que, se encurntar desplegada en un contenedor Docker Gunicorn, utilizando Nginx como Proxy inverso.

## Estructura general del directorio:

- Pythia/
  - app/
    - main/
      - code/
        - controllers/
          - admin/
          - auth/
          - main/
          - rag/
        - inetrnacionalizacion/
        - model/
        - services/
          - markdown/
          - rag/
          - web_scraping/
          - documentos.py
          - async_tasks.py
          - markdown_conversion_state.py
          - vector_update_state.py
          - web_scraping_state.py
        - __init__.py
        - countries.py
        - decorators.py
        - extensions.py
        - forms.py
        - run.py
      - resources/
        - static/
        - templates/
    - test/
      - integration/
      - unit/
      - support.py
      - run_tests.sh
  - migrations/
  - docker/
    - nginx/
      - nginx.conf.template
  - docker-compose.yml
  - Dockerfile
  - entrypoint.sh
  - requirements_docker.txt

## Contenido de los archivos y directorios:
- **app/main/code**: contiene el código Python real de la aplicación Flask. Concretamente los controladores, modelos, formularios, servicios, web scraping, RAG y el punto de entrada `run.py`.
- **app/main/code/controllers**: contiene los controladores y blueprints de la aplicación.
- **app/main/code/services**: contiene la lógica de servicio de la aplicación, incluyendo RAG, conversión a Markdown, web scraping, tareas asíncronas y gestión de documentos.
- **app/main/code/model**: contiene los modelos y entidades de dominio de la aplicación.
- **app/test**: contiene los tests unitarios y de integración de la aplicación, además de utilidades compartidas y el script `run_tests.sh` que sirve para ejecutar los **tests**.
- **migrations**: esta carpeta contiene el historial de vesrisones de la base de datos (gestionado con Flask-Migrate/Alembic). Estas migraciones sirven para aplicar de forma automática los cambios de la base de datos en cualquier entorno. 
- **docker/nginx**: contiene la configuración del servidor Nginx. Nginx actúa como proxy inverso delante de la aplicación Flask.
- **app/main/resources/static**: almacena los archivos estáticos (CSS, JavaScript e imágenes).
- **app/main/resources/templates**: contiene las plantillas HTML que Flask renderiza con Jinja2.
- **docker-compose.yml**: en este archivo se define la arquitectura de la aplicaicón en contenedores Docker. También, indica como se relacionan entre ellos dichos contenedores. Se encarga de levantar la base de datos sql (db) con PostgreSQL, con un volumen persisitente, la base de datos vectorial (qdrant), y un LLM local (Ollama). Además, el servicio de Ollama descarga y verifica automaticamente los modelos configurados en RAG_LLM_MODELS y el modelo OCR antes de que arranque la web. El servicio principal es el de web, el cual construye la app Flask propiamente dicha. Espera a que los servicios esten listos y configura las variables (URL Ollama, qdrant y el directorio de documentos). Se ejecuta con Gunicorn y Nginx (exponiendo el puerto 80). TambiÃ©n, define un servicio para los test, los cuales utilizan SQLite en memoria. Por Ãºltimo, define volÃºmenes persistentes como Postgres, Qdrant, Ollama, cachÃ© de HuggingFace y datos para que la informaciÃ³n no se pierda al reiniciar los contenedores. 
- **Dockerfile**: en este archivo se define como se contruye la imagen docker de la aplicaicón. En este caso parte de la imagen "mcr.microsoft.com/playwright/python:v1.57.0-jammy" la cual ya incluye Python y Playwright. Establece /app como el directorio de trabajo e instala las dependecnais del sistema para compilar paquetes Python y conectarse a PostgreSQL. Las dependencias las instala desde el archivo "requirements_docker.txt" (copiandolo para aprovechar la caché del Docker). Después, de instalar las dependencias copia el código del proyecto dentro del contenedor y expone el puerto 5000 (donde corre Gunicorn) y estaablece el script entrypoint.sh como inicio del contenedor.
- **entrypoint.sh**: es el archivo que se ejecuta cuando arranca el contenedor de la aplicación (web) encargandose de preparar el entorno. Se encarga de construir la variable DATABASE_URL y esperar a que PostgreSQL y Qdrant estén disponibles. Una vez que las bases de datos están listas aplica las migraciones. Por último, inicia el servidor en producción usando Gunicorn.
- **requirements_docker.txt**: en este documento se listan las dependencias necesarias para ejecutar la aplicaicón dentro del contenedor Docker. Utilizando este archivo cuanado se cosntruye la imagen se instalan automáticamente todas las librerias necesatioas para su ejecución. 
- **app/main/code/run.py**: este archivo sirve como punto de entrada a la aplicación Flask. Se encarga de importar `create_app()`, crear la instancia de la aplicación y exponerla como variable `app`.


## Ejecución de los archivos:
En este apartado se van a indicar los pasos para ejecutar la aplicación web. 
Para aceder a la página web ya levantada en el servidor solo se tiene que acceder al dominio pythia.es:

[PythIA](https://pythia.es)

Si se desea, también es accesible (si se está conectado a Eduroam) desde la IP del servidor:

[PythIA (10.168.168.12)](http://10.168.168.124/) 

Si se desea desplegar en local se puede levantar usando los siguienets comandos.
  - Este primer comando permite levantar la aplicación recostruyendo el código (ideal para la primera ejecución). Va a contruir las imágenes y levantar los contenedores:
    ```bash
    docker compose up --build  
    ```
  - Si solo se desea recsotruir las imágenes sin levnatar lso contenedores se puede usar el comando compose sin el up:
    ```bash
    docker compose build  
    ```
  - Para que recostruya el código sin usar el chache almacenado por Docker (recomendado si hay fallos de dependencias):
    ```bash
    docker compose build --no-cache
    ```
  - Para levantar la aplicaicón sin recostruir el código. Utilizando las imagnees contruidas previamente.:
    ```bash
    docker compose up 
    ```

Para parar los contenedores se pueden usar dos comando.
  - El priemro permite detener los contenedores manteniendo los volúmenes y datos:
    ```bash
    docker compose down
    ```
  - Si además se desea eliminar los volúmenes y los datos (incluyendo bases de datos y archivos guardados):
    ```bash
    docker compose down --volumes
    ```

Si se desesa borrar el cache de los builds pero manteniendo los contenedores y las imagenes acticas se usa:
```bash
docker builder prune -af
```
Si se desea realizar una limpieza completa del Docker, incluyendo los contenedores parados, las iamgenes no usadas, el caché y los volumenes se puede usar este copmando:
```bash
docker system prune -af --volumes
```
Para ver los logs de la aplicación se puede usar el comando:
```bash
docker compose logs -f
```
Para reiniciar servicios se puede usar el comando:
```bash
docker compose restart
```

NOTA: para que funcione el despliegue en local debe estar instalada en el sistema la función docker. 

Para instalar docker en Ubuntu se debe:
1) Instalar dependencias:
   ```bash
   sudo apt install ca-certificates curl gnupg lsb-release -y
   ```
2) Instalar docker:
   ```bash
   sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
   ```
Se puede confirmar la instalación mirando la versión que hay de docker instalada en el sistema. Si devuelve una ersión es que se ha instalado correctamete.
```bash
docker --version
```

Para instalar docker en Windows se puede descargar direcrtaemnte la aplicación de escritorio de la página oficial de [docker](https://www.docker.com/products/docker-desktop/). 
De igual forma que en Ubuntu se puede confirmar la instalacióne jecuantando el comando:
```powershell
docker --version
```
s
