# PROTOTIPOS

Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentran los archivos de prueba que se han ido generando durante el desarrollo del proyecto. 

## Estructura general del directorio:

- BaseDatos.py
- Prompt.py
- PruebaBaseDatos.py
- PrototipoRAG.py
- Flask/
  - app/
  - migrations/
  - static/
  - tests/
  - templates/
  - docker-compose.yml
  - Dockerfile.qdrant
  - requirements.txt
  - app.db
  - Dockerfile
  - entrypoint.sh
  - requirements_docker.txt
  - run.py
- Flask_docker/
  - app/
  - migrations/
  - nginx/
  - static/
  - tests/
  - templates/
  - docker-compose.yml
  - Dockerfile.qdrant
  - Dockerfile
  - entrypoint.sh
  - requirements_docker.txt
  - run.py
- Markdown/
  - Intento1_Markdown.py
  - Markdown_Ocr.py
  - Markdown_Ollama.py 
  - Markdown_Ollama2.py
  - markdown/
  - markdown_Ocr/
  - markdown_Ollama/
  - pdfs/
- tokenizers/
  - script_tokenize.py
  - script_tokenizer1.py
  - script_tokenizer3.py
  - script_tokenize_segundoModelo.py
  - resumen2.json
  - resumen3.json 
- Web Scraping/
  - DescargarPdf.py
  - DescargarPliegos.py
  - PliegosPlaywrightAsincrono.py
  - PliegosPlaywright.py
  - PliegosSelenium.py
  - pliegos_pdfs.json
  - resultados_playwright_asincrono.json
  - resultados_playwright_asincrono_servidor.json
  - resultados_playwright.json
  - resultados_Selenium.json 

## Contenido de los archivos y directorios:
- BaseDatos.py: contruye la base de datos vectorial que va a usar el modelo RAG para búsquedas semánticas posteriores. Para ello carga un modelo de embeddings (SentenceTransformers), y, además, crea y gestiona una base de datos vectorial local (Qdrant). Concretamente recorre una carpeta de PDF (llamada <<pliegos>>) extrayendo el texto de cada documento y dividiendolos en fragmentos (chunks) según el límite de tokens del modelo. Por cada chunks calcula sus embeddings y lso almacena en Qdrant con metadatos. 
- Prompt.py: es un script que permite interactuar con el prototipo RAG mediante la terminal. Pide preguntas al usuario en bucle y genera las respuestas usando un modelo LLM (llama3.1). Para recuperar los fragametos más relevantes y pasarselos al LLM como promt aumentado utiliza la función obtener_mejor_chunk de la clase PrototipoRAG. Finalmente muestra la respuesta por pantalla junto con los metadatos del chunk utilizado (título, fichero, índice del segmento y el texto recuperado).
- PruebaBaseDatos.py: este script se encarga de comprobar el contenido de la base de datos vectorial. Recupera hasta 1000 documentos almacenados en dicha base de datos (Qdrant) usando VectorBaseDocument.bulk_find. Para motrar por consola la lista de archivos ya indexados extrae de los metadatos de los chunks recuperados el nombre del fichero. 
- PrototipoRAG.py: este script se corresponde con un primer prototipo de la implementación del RAG completo. Carga el modelo de embedding, gestiona la base de datos vectorial (Qdrant), divide los PDFs en chunks con solapamiento, calcula sus embeddings y permite recuperar por similiud semántica. Para generar la respuesta integra Ollama como LLM. A este modelo se le pasa un promp aumnetado con la pregunta del usuario y el chunk más relevante, además, se le especifica que responda en español. Aparte de recuperar el fragmento más parecido a una pregunta y generar la respuesta a partir de ese contexto, también recostruye la base de datos vectorial letendo los PDF de la carpeta pliegos (tal y como hace el script BaseDatos).
- Flask: en esta carpeta se encuentra el primer prototipo de la web desarrollada con Flask. Este prototipo es una aplicación funcional con interfaces, login, gestión de usuarios y penel de administarción, estructurada por blueprints (main, auth, admin, rag). Pero que se ejecuta en un servidor de pruebas (aunque se comenzó aqui el despliegue de Docker no está completo). Como base de datos utiliza SQLLite.
- Flask_docker: en esta carpeta se encuentra la versión preparada para producción de la aplicación web RAG, adaptada para ejecutarse en un contenedor Docker con Nginx y Gunicorn. Permitiendo desplegar la aplicación completa (web, base de datos sql y vectorial) en contenedores facilitando su ejecución. Como base de datos utiliza PostgresSQL. Además, tiene soporte para envio de correos con Flask-Mail.
- Markdown: en esta carpeta hay varios prototipos para convertir PDF a Markdown estructurado. Se prueban distintas estrategias, entre ellas, MarkItDown con reglas de postprocesado para detectar títulos, secciones e ínidces automáticamente. También, se prueba con la biblioteca PyMuPDF y  OCR con TrOCR (de Hugging Face) como respaldo cuando el PDF no tiene texto embebido. Otra versión utiliza Ollama con el modelo Nanonets-OCR para generar directamente Markdown limpio a partir de imágenes del PDF, incluyendo reglas de formateo de tablas y encabezados. 
- tokenizers: en esta carpeta se prueba con varias formas de procesar PDF largos dividiendolos y generando resúmenes estructurados por apartados usando modelos LLM. De forma general, los scripts leen el PDF, normalizan el texto (limpiando índices y cabeceras) y buscan las secciones (mediante heurística simple, numeración, mayúsculas, etc). Después, fragmentan el texto respetando límites de tokens con solapamiento. 
- Web Scraping: en esta carpeta hay varias implemenatciones de scripts para recopilar de manera automática licitaciones y descargar sus documentos (pliegos) desde la Plataforma de Contratación del Sector Público. En dichos scripts se prueba tanto Selenium como Playwright síncorno y asíncrono para navegar por la web, seleccionar el órgano de contratación, recorrer las licitaciones, extraer sus metadatos y guardar los resultados (en un fichero JSON). También, se incluyen archivos que recorren estos JSON para entrar en las páginas de los documentos y descargar los pliegos en formato PDF.  

## Ejecución de los archivos:
Para ejecutar los archivos de web scraping de la carpeta hay que usar el comando:
pip install -r requirements.txt

Posteriormente hay que instalar los navegadores de playwright con el siguiente comando:
playwright install chromium

Para ejecutar el archivo hay que usar:
 python NombreDelArchivo.py
