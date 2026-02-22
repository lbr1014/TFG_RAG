# TOKENIZERS
Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentran los archivos de prueba que se han generado para probar distintos tokenizers y entender su funcionamiento.

## Estructura general del directorio:

- tokenizers/
  - script_tokenize.py
  - script_tokenize_segundoModelo.py
  - script_tokenizer1.py
  - script_tokenizer3.py
  - resumen2.json
  - resumen3.json
  - pruebas.pdf
 
 ## Contenido de los archivos y directorios:

- **script_tokenize.py**: este script se encarga de dividir el texto de los documentos en fragmentos más pequeños (tokenizar). Es una parte del sistema RAG. Toma como entrada os PDF (extaridos de web scraping), los limpia y segmenta por el número de caracteres. Genera una lista para ser indexada en una base de datos vectorial. 
- **script_tokenize_segundoModelo.py**: este script es uan variante del proceso de tokenización con una configuración alternativa de embeddings. Su función principal es procesar los textos de los documentos, limpiarlos y dividirlos en fragmentos adecuados (según el limite de tokens del modelo). Genera los tokens que posteriormente se van a convertir en vectores e indexar en la base de datos vectorial. 
- **script_tokenizer1.py**: este script se encarga de procesar y fragmentar textos en chunks listos para generar embeddings. Es una primera versión donde se definene reglas de limpieza, segmentación y tamaño de los fragmentos. 
- **script_tokenizer3.py**: este script es otra variante del proceso de tokenización. Su función principal es limpiar lso documentos y dividirlos en fragmentos optimizados para generar embeddings y almacenarlos en una base de datos vectorial. En esta versión se incluye guardado de metadatos y solapamiento para mayor contexto de los chunks. 
- **resumen2.json**: este archivo JSON contienen los dats generados en el pipeline de procesamiento. Contiene resúmenes estructurados de los documentos. Recoge información sintetizada a partir de los textos ya procesados. 
- **resumen3.json**: este archivo JSON es otro arhcivo de dalida del pipelie. Contiene resumenes generados automáticamente de lso documentos. Almacena información sintetizada y fácil de consultar que complemente los textos originales y los embeddings, permitiendo comparar resultados.
- pruebas.pdf: este archivo es un pliego en pdf para hacer pruebas del tokenizado con lso distientos scripts.
 
## Ejecución de los archivos:
En este apartado se van a indicar los pasos para ejecutar los archivos de web scraping, tanto desde una terminal Ubuntu como desde la terminal de Windows. 
### Ejecutar desde Ubuntu:
Se van a describir dos formas de instalar las dependecias para ejecutar los programas desde una terminal Ubuntu. La primera opción consiste en usar Poetry y la segunda el archivo requirements.
##### Utilizando Poetry:
1)  Comprobar que esta descargado en el sistema Python:
  
    ```bash
    python3 --version
    ```
    
    Si no está instalado, hay que instalarlo. Para ello ejecutar:
    
    ```bash
    sudo apt update
    sudo apt install python3 python3-pip python3-venv git -y
    ```

2) Comprobar que Poetry esta instalado:
    ```bash
    poetry --version
    ```
    
    Sino esta instalado hay que instalarlo, para ello ejecutar:
    
    ```bash
    curl -sSL https://install.python-poetry.org | python3 -
    ```
   
3) Entrar al directorio del proyecto:
   ```bash
   cd TFG_RAG/prototipos/tokenizers
   ```
4) Instalar las dependencias:
   ```bash
   poetry install
   ```
5) Activar entorno virtual:
    - Si tu versión de poetry es anterior a la 2.0.0 ejecuta:
      ```bash
      poetry shell
      ```
    - Si es posterior a a versión 2.0.0 ejecuta:
      ```bash
      poetry env activate
      ```
      Para activar el entorno se debe copiar lo que te devuelve por consola el comando devuelto será algo parecuido a este:
      ```bash
      source /direccion /.venv/bin/activate
      ```
      Para salir del entorno virtual se ejecuta:
      ```bash
      deactivate
      ```
6) Ejecutar alguno de los scripts:
   ```bash
   python nombreArchivo.py
   ```

##### Utilizando requirements.txt:
1) Crear un entorno virtual (.ven):
   ```bash
   python3 -m venv .venv
   ```
2) Activar el entorno virtual:
   ```bash
   source .venv/bin/activate
   ```
3) Instalar el requirements.txt:
   ```bash
   pip install -r requirements.txt 
   ```
4) Ejecutar alguno de los scripts:
   ```bash
   python nombreArchivo.py
   ```

### Ejecutar desde Windows:
Se van a describir dos formas de instalar las dependecias para ejecutar los programas desde una terminal Windows. La primera opción consiste en usar Poetry y la segunda el archivo requirements.
##### Utilizando Poetry:
1)  Comprobar que esta descargado en el sistema Python:
  
    ```powershell
    python --version
    ```
    
    Si no está instalado, hay que instalarlo. Se puede instalar desde la página oficial de [Python]([URL](https://www.python.org/downloads/))
2)  Comprobar que esta descargado en el sistema Poetry:
  
    ```powershell
    poetry --version
    ```

    En caso de que no este instalado hay que ejecuatr este comando para intalarlo y después cerrar la terminal y volverla a abrir:
    ```powershell
    (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -
    ```
3) Una vez que Python y Poetry estan instalados hay que ir al directorio:
   ```powershell
   cd direccion
   ```
4)  Instalar las dependencias:
   ```powershell
   poetry install
   ```
5) Activar entorno virtual:
    - Si tu versión de poetry es anterior a la 2.0.0 ejecuta:
      ```powershell
      poetry shell
      ```
    - Si es posterior a a versión 2.0.0 ejecuta:
      ```powershell
      poetry env activate
      ```
      Para activar el entorno se debe copiar lo que te devuelve por consola el comando devuelto será algo parecuido a este:
      ```powershell
      & "C:\direccion\.venv\Scripts\activate.ps1"
      ```
      Para salir del entorno virtual se ejecuta:
      ```powershell
      deactivate
      ```
6) Ejecutar alguno de los scripts:
   ```powershell
   python nombreArchivo.py
   ```
##### Utilizando requirements.txt:
1) Crear un entorno virtual (.ven):
   ```powershell
   python -m venv .venv
   ```
2) Activar el entorno virtual:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
3) Instalar el requirements.txt:
   ```powershell
   pip install -r requirements.txt 
   ```
4) Ejecutar alguno de los scripts:
   ```powershell
   python nombreArchivo.py
   ```
    
