# Rostros conocidos de Diver

Usa una carpeta por persona:

```text
data/faces/
  Diego/
    01.jpg
    02.jpg
    03.png
  Laura/
    frente.jpg
    sonrisa.jpg
```

Recomendaciones:

- Usa 3 a 8 fotos por persona.
- Que salga una sola cara clara por foto.
- Mezcla angulos suaves: frente, un poco izquierda, un poco derecha.
- Evita gafas oscuras, tapabocas, blur o fotos muy lejanas.
- Usa fotos de personas que dieron permiso para ser registradas.

Despues de agregar fotos, reinicia el backend o llama:

```bash
curl -X POST http://localhost:5000/api/faces/reload
```

Tambien puedes subir por API con `multipart/form-data`:

```bash
curl.exe -X POST http://localhost:5000/api/faces/upload `
  -F "person=Diego" `
  -F "photos=@C:\ruta\a\foto1.jpg" `
  -F "photos=@C:\ruta\a\foto2.jpg"
```
