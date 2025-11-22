
from PrototipoRAG import obtener_mejor_chunk

if __name__ == "__main__":
    while True:
        pregunta = input("Pregunta (enter para salir): ").strip()
        if not pregunta:
            break

        result = obtener_mejor_chunk(pregunta, model="llama3.1:8b-instruct-q4_K_M")

        print("\n=== Respuesta del LLM ===")
        print(result["answer"])
        print("\n=== Metadatos del chunk ===")
        print("Título:", result["title"])
        print("Fichero:", result["filename"])
        print("Segmento:", result["segment_index"])
        print("\n=== Chunk usado ===")
        print(result["chunk"])
        print("\n" + "=" * 60 + "\n")
