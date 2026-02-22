# WEB SCRAPING
Autora: Lydia Blanco Ruiz.

En esta carpeta se encuentran los archivos de prueba que se han ido generando para automatizar la descarga de los pliegos del estado de la [ Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/).
Se prueba tanto Selenium como Playwright síncorno y asíncrono para navegar por la web, seleccionar el órgano de contratación, recorrer las licitaciones, extraer sus metadatos y guardar los resultados (en un fichero JSON). También, se incluyen archivos que recorren estos JSON para entrar en las páginas de los documentos y descargar los pliegos en formato PDF.

## Estructura general del directorio:

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
- **DescargarPdf.py**: este script usa Playwright en modo asíncrono para leer un archivo JSON (resultados_playwright_asincrono_servidor.json). Para cada expediente almacenado en el archivo se entra en la página guardada desde la cual se descarga el pdf en español del pliego y luego se almacena en la carpeta pdfs. el espediente se guarda con el nombre del espediente.
- **DescargarPliegos.py**: este script automatiza la búsqueda y descarga de pliegos en PDF a partir de un archivo JSON (resultados_playwright_asincrono_servidor.json) utilizando Plawright asíncrono. Para cada registro coge el expediente de aquellos que tengan pliegos. Para estos entra en la URL y descarga los dos tipos de pliegos (Pliego Prescripciones Técnicas y Pliego Cláusulas Administrativas) y los almacena en la carpeta Pliegos.
- **PliegosPlaywrightAsincrono.py**: este script automatiza la extración de la información de los expedientes de la Junta de Gobierno de la Diputación Provincial de Burgos usando Playwright asíncorno. Para ello entra en la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/), navega hasta Perfil Contratante, selecciona el organo (la junta de Burgos) y selecciona las licitaciones. 
- **PliegosPlaywright.py**:  este script automatiza la extración de la información de los expedientes de la Junta de Gobierno de la Diputación Provincial de Burgos usando Playwright síncorno. Para ello entra en la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/), navega hasta Perfil Contratante, selecciona el organo (la junta de Burgos) y selecciona las licitaciones. 
- **PliegosSelenium.py**: este script automatiza la extración de la información de los expedientes de la Junta de Gobierno de la Diputación Provincial de Burgos usando Selenium. Al igual que los otros, entra en la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/), navega hasta Perfil Contratante, selecciona el organo (la junta de Burgos) y selecciona las licitaciones. 
- **pliegos_pdfs.json**: este archivo es uno de los JSON que se generan al ejecutar los scripts anteriores, concretamente el de DescaragrPliegos. En él se guardan las URL de los PDF de los pliegos encontrados para cada expediente. Su estructura es un diccionario donde las claves son los identificadores del expediente y el valor es una lista con los pliegos (Pliego Prescripciones Técnicas y Pliego Cláusulas Administrativas).
- **resultados_playwright_asincrono.json**: este archivo es el primer JSON que se generó con el script PliegosPlaywrightAsincrono. En él se guarda la infromación de los expedientes obtenida de la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/). Su estructura es una lista de objetos donde cada elemento es una licitación con dos bloques, el de datos con la información del expediente y el de documentos. Este archivo sirve como entrada para los scripts que descargan PDF (DescargarPdf y DescargarPliegos).
- **resultados_playwright_asincrono_servidor.json**: este archivo se genera al ejecutar el script PliegosPlaywrightAsincrono. En él se guarda la infromación de los expedientes obtenida de la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/). Su estructura es una lista donde por cada expediente se guarda un bloque de datos con toda la información del expediente y un bloque documentos con le nombre y URL de todos los documentos asociados. Este archivo sirve como entrada para los scripts que descargan PDF (DescargarPdf y DescargarPliegos).
- **resultados_playwright.json**: este archivo se genera al ejecutar el script PliegosPlaywright. Contiene una lista de expedientes obtenidos de la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/). Al igual que en el caso anterior, por cada elemento se alamcenan los datos y los documentos asociados. Este archivo sirve como entrada para los scripts que descargan PDF (DescargarPdf y DescargarPliegos).
- **resultados_Selenium.json**: este archivo se genera al ejecutar el script PliegosSelenium. Contiene una lista de expedientes obtenidos de la [Plataforma de Contratación del Sector Público](https://contrataciondelestado.es/wps/portal/plataforma/inicio/!ut/p/z1/04_Sj9CPykssy0xPLMnMz0vMAfIjo8zinYItLBydDB0NDIxDLQwczQIDnS1dDIwMLI31wwkpiAJKG-AAjgZA_VFgJabGziZhXmEBZsGe7gYGnh5uLj6hhqYG7kZmUAV4zCjIjTDIdFRUBAD_nKPx/dz/d5/L2dBISEvZ0FBIS9nQSEh/), donde por cada uno se almacenan los datos del expediente y los documentos relacionados. Este archivo sirve como entrada para los scripts que descargan PDF (DescargarPdf y DescargarPliegos).

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
   cd TFG_RAG/prototipos/'Web Scraping'
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
    
