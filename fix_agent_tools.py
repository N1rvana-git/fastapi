with open("src/posts/agent_tools.py", "r") as f:
    text = f.read()

text = text.replace('embed_response = chat_client.embeddings.create(model="text-embedding-004", input=query)\n        query_vector = embed_response.data[0].embedding', 'embed_response = chat_client.embeddings.create(model="text-embedding-004", input=query)\n        query_vector = embed_response.data[0].embedding')
