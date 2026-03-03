# PythIA - Aplicaicón final

Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentra la versión final de la aplicaicón. Esta preparada para ejecutarse desde cualquier dispositivo sin la necesidad de gestionar sus dependencias, ya que, se encurntar desplegada en un contenedor Docker Gunicorn, utilizando Nginx como Proxy inverso.

## Estructura general del directorio:

- Pythia/
  - app/
    - admin/
    - auth/
    - main/
    - rag/
    - web_scraping/
    - __init__.py
    - async_tasks.py
    - chunk.py
    - consulta.py
    - consultaChunk.py
    - decorators.py
    - documentos.py
    - embedding.py
    - extensions.py
    - forms.py
    - usuario.py
    - vector_update_state.py
    - web_scraping_state.py
  - migrations/
  - nginx/
    - nginx.conf
  - static/
    - css/
      - estilos.css
    - js/
      - bar_progress.js
      - functionalities.js
  - templates/
    - admin_create_user.html
    - admin_documents.html
    - base.html
    - edit_user.html
    - forgot_password.html
    - history.html
    - index.html
    - login.html
    - pag_principal.html
    - rag.html
    - reset_password.html
    - singup.html
    - tabla_historial.html
    - users.html
  - tests/
    - test_admin/
    - test_auth/
    - test_main/
    - test_rag/
    - test_web_scraping/
    - __init__.py
    - test_async_tasks.py
    - test_chunk.py
    - test_consulta.py
    - test_consultaChunk.py
    - test_decorators.py
    - test_documentos.py
    - test_embedding.py
    - test_forms.py
    - test_init.py
    - test_usuario.py
    - test_vector_update_state.py
    - test_web_scraping_state.py
  - docker-compose.yml
  - Dockerfile
  - entrypoint.sh
  - requirements_docker.txt
  - run.py

## Contenido de los archivos y directorios:
- **app**: en esta carpeta se encuentra el núcleo de la aplicaicón web, continene la lógica del programa. Concretamente se definen los modelos (usuario, consulta, socumentos), los servicios y las extensiones (bases de datos, login, migraciones y correo). Además, contiene la lógica de las tareas asincronas, del web scraping y el propio sistema RAG. 
- **migrations**: en esta carpeta esta almacenado el historial de vesrisones de la base de datos (gestionado con Flask-Migrate/Alembic). Estas migraciones sirven para aplicar de forma automática los cambios de la base de datos en cualquier entorno. 
- **nginx**: en esta carpeta esta definida la configuración del servidor Nginx. Nginx actúa como un proxy inverso delante de la aplicación Flask. Definiendo cómo se reciben las peticiones HTTP/HTTPS, el manejo de dominios, certificados SSL, compresión, caché y los envios al contenedor donde corre la aplicación (Gunicorn). 
- **static**: en esta carpeta se almacenen los archivos estáticos (css, java script e imágenes). Estos archivos se descargan automáticamente sin pasar por lógica de backend.  
- **templates**: en esta carpeta estan las plantillas HTML de la aplicación que Flask renderiza utilizando Jinja2. Concretamente se encuentran las páginas de autenticación (inicio de sesión, registro y recuperación de contraseña), las de gestión del administardor (de usuarios y documentos), el hsitorial de consultas y la interfaz de consultas.
- **tests*: en esta carpeta se encuentran los test unitarios  y de integración de la aplicación. Estos tets cubren todas las clases de la carpeta app. Se ejecutan como un volumne del docker generando el coverage cada vez.
- **docker-compose.yml**: en este archivo se define la arquitectura de la aplicaicón en contenedores Docker. También, indica como se relacionan entre ellos dichos contenedores. Se encarga de levantar la base de datos sql (db) con PostgreSQL, con un volumen persisitente, la base de datos vectorial (qdrant), y un LLM local (Ollama). Además, se incluye un servicio para iniciar Ollama (ollama-init), el cual se encarga de descargar el modelo (llama3.1 8B instruct). El servicio principal es el de web, el cual construye la app Flask propiamente dicha. Espera a que los servicios esten listos y configura las variables (URL Ollama, qdrant y el directorio de documentos). Se ejecuta con Gunicorn y Nginx (exponiendo el puerto 80). También, define un servicio para los test, los cuales utilizan SQLite en memoria. Por último, define volúmenes persistentes como Postgres, Qdrant, Ollama, caché de HuggingFace y datos para que la información no se pierda al reiniciar los contenedores. 
- **Dockerfile**: en este archivo se define como se contruye la imagen docker de la aplicaicón. En este caso parte de la imagen "mcr.microsoft.com/playwright/python:v1.57.0-jammy" la cual ya incluye Python y Playwright. Establece /app como el directorio de trabajo e instala las dependecnais del sistema para compilar paquetes Python y conectarse a PostgreSQL. Las dependencias las instala desde el archivo "requirements_docker.txt" (copiandolo para aprovechar la caché del Docker). Después, de instalar las dependencias copia el código del proyecto dentro del contenedor y expone el puerto 5000 (donde corre Gunicorn) y estaablece el script entrypoint.sh como inicio del contenedor.
- **entrypoint.sh**: es el archivo que se ejecuta cuando arranca el contenedor de la aplicación (web) encargandose de preparar el entorno. Se encarga de construir la variable DATABASE_URL y esperar a que PostgreSQL y Qdrant estén disponibles. Una vez que las bases de datos están listas aplica las migraciones (```flask db upgrade```). Por último, inicia el servidor en producción usando Gunicorn (que escucha el puesrto 0.0.0.0:5000 con 2 workers y 4 hlos por worker).
- **requirements_docker.txt**: en este documento se listan las dependencias necesarias para ejecutar la aplicaicón dentro del contenedor Docker. Utilizando este archivo cuanado se cosntruye la imagen se instalan automáticamente todas las librerias necesatioas para su ejecución. 
- **run.py**: este archivo sirve como punto de entrada a la palicaicón Flask. Se encarga de importar la función create_app() del paquete app, crear la instancia de la aplicación y la expone como variable app. Luego la utiliza Gunicorn para levantar el servidor en producción. 

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

