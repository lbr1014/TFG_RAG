# Flask_docker

Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentran la versión preparada para producción de la aplicación web RAG, adaptada para ejecutarse en un contenedor Docker con Nginx y Gunicorn.

## Estructura general del directorio:

- Flask_docker/
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
  - Dockerfile.qdrant
  - Dockerfile
  - entrypoint.sh
  - requirements_docker.txt
  - run.py

## Contenido de los archivos y directorios:

## Ejecución de los archivos:
En este apartado se van a indicar los pasos para ejecutar la aplicación web. 
Para aceder a la página web ya levantada en el servidor solo se tiene que acceder aesta dirección:
[RAG sobre licitaciones del estado](http://10.168.168.124/)

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
