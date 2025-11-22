from PrototipoRAG import VectorBaseDocument

docs, _ = VectorBaseDocument.bulk_find(limit=1000)

nombres = {d.metadata.get("filename") for d in docs}
print("Ficheros distintos en la colección:")
for nombre in sorted(nombres):
    print("-", nombre)
