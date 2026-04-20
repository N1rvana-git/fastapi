import os

files = [
    "src/posts/agent_tools.py",
    "src/posts/service.py",
    "src/feishu/router.py",
    "src/posts/ingest_doc.py"
]

for file in files:
    with open(file, "r") as f:
        content = f.read()
    
    # Replace the embedding model
    content = content.replace('model="text-embedding-004"', 'model="text-embedding-ada-002"')
    content = content.replace("768", "1536") # Also adjust any comments
    
    with open(file, "w") as f:
        f.write(content)

# Update models.py for pgvector dimension
with open("src/posts/models.py", "r") as f:
    content = f.read()

content = content.replace("Vector(768)", "Vector(1536)")

with open("src/posts/models.py", "w") as f:
    f.write(content)

print("Files updated for text-embedding-ada-002 (1536 dims).")
