import requests

def delete():
    response = requests.delete('http://localhost:8000/items/ai/history')
    print(response.status_code)
    print(response.text)

if __name__ == "__main__":
    delete()
