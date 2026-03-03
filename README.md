# PythIA 
Autora: Lydia Blanco Ruiz.
<p align="center">
  <img width="300" height="300" alt="PythIA_def" src="https://github.com/user-attachments/assets/6e44a4d9-eb22-4aba-a984-b625981c8ded" />
</p>

**PythIA** es una aplicación que permite realizar consultas sobre las licitaciones del estado, concretamente de la **Junta de Gobierno de la Diputación Provincial de Burgos**. Las respuestas se generan usando un ***LLM***  (*Large Lenguaje Model*) alimentado por un modelo ***RAG*** (*Retrieval-Augmented Generation*) que busca información concreta de los pliegos de la Junta.

Se puede acceder a la aplicación desde cualquier navegador accediendo a la dirección:
> [https://pythia.es](https://pythia.es/)

## Despliegue en local
Para el despliegue en local debe estar instalado en el sistema  <a href="#instalarDocker">*docker*</a> y <a href="#instalarGit">*git*</a>.
### ⚙️ Instalar *docker*
<a id="instalarDocker"></a>
Para instalar *docker* en ***Ubuntu*** se debe:
   1) Instalar dependencias:
      ```bash
      sudo apt install ca-certificates curl gnupg lsb-release -y
      ```
   3) Instalar docker:
      ```bash
      sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
      ```

Para instalar *docker* en ***Windows*** se puede descargar direcrtaemnte la aplicación de escritorio de la página oficial de [*docker*](https://www.docker.com/products/docker-desktop/). 

> Se puede confirmar la instalación mirando la versión que hay de *docker* instalada en el sistema. Si devuelve una versión es que se ha instalado correctamete.
>  ```bash
>  docker --version
>  ```
### ⚙️ Instalar *git*
<a id="instalarGit"></a>

