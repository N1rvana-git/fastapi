with open("docker-compose.yml", "r") as f:
    text = f.read()

text = text.replace("volumes:\n  pgdata:", "volumes:\n")
text = text.replace("volumes:", "volumes:\n  pgdata:\n")

with open("docker-compose.yml", "w") as f:
    f.write(text)
