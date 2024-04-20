import os
import docx2txt
import ollama as ol
import base64
import fitz
from llama_index.embeddings.ollama import OllamaEmbedding
#from llama_index.core.embeddings import resolve_embed_model
from llama_index.llms.ollama import Ollama
import os.path
from llama_index.core import Document, Settings, VectorStoreIndex, StorageContext, load_index_from_storage, SimpleDirectoryReader
from llama_index.vector_stores.postgres import PGVectorStore
import ocrmypdf
import psycopg2
from sqlalchemy import make_url

directory_path = "./data-small"
image_path = "./img"
documents = []

pt1 = "Provide a detailed description of the image by identifying the key elements present, such as any subjects, objects, or significant aspects of the environment. Describe any actions, interactions, or dynamics you observe, and detail the setting and context, noting the location, time of day, and any environmental conditions. Interpret any emotional tone, mood, or themes conveyed through expressions, atmosphere, or composition. Highlight any unique, unusual, or particularly striking features or details. Aim to give a comprehensive overview that encapsulates the essence of the image."

###### Model Settings ######
Settings.embed_model = ollama_embedding = OllamaEmbedding(model_name="nomic-embed-text",base_url="http://localhost:11434", ollama_additional_kwargs={"mirostat": 0},)
Settings.llm = Ollama(model="mistral", request_timeout=30.0)
###### End Model Settings ######

###### DB Connection ######
connection_string = "postgresql://postgres:postgres@localhost:5432/postgres" # Test connection string
db_name = "uplest_db"
conn = psycopg2.connect(connection_string)
conn.autocommit = True

# Delete the existing DB if desired

with conn.cursor() as c:
    c.execute(f"DROP DATABASE IF EXISTS {db_name}")
    c.execute(f"CREATE DATABASE {db_name}")

url = make_url(connection_string)
vector_store = PGVectorStore.from_params(
    database=db_name,
    host=url.host,
    password=url.password,
    port=url.port,
    user=url.username,
    table_name="test_table",
    embed_dim=768,  # bge embedding dimension
)

###### End DB Connection ######



"""
Function: caption_docx_image_documents

Captions an image by generating a description using the Llava Multimodal Model.

Args:
    image (str): Filename of the image.
    file_origin (str): Originating document name.
"""
def caption_docx_image_documents(image, file_origin):
        with open(image_path+"/"+file_origin+"/"+image, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read())
        response = ol.generate(model='llava', prompt=pt1, images=[encoded_string])
        #print(response['response'])
        summary = f"\nImage Name: {file_origin}.docx\nDescription: {response['response']}\n\n"
        document = Document(text=summary,metadata={"file_name": file_origin+".docx"})
        documents.append(document)

"""
Function: caption_image_file

Captions an image by generating a description using the Llava Multimodal Model.

Args:
    image_fname (str): Filename of the image.
"""

def caption_image_file(image_fname):
    with open(image_fname, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read())
            response = ol.generate(model='llava', prompt=pt1, images=[encoded_string])
            #print(response['response'])
            summary = f"\nImage Name: {image_fname}\nDescription: {response['response']}\n\n"
            document = Document(text=summary,metadata={"file_name": image_fname})
            documents.append(document)

"""
Function: process_docx_and_extract_images

Processes a DOCX file to extract text and images.

Args:
    docx_path (str): Path to the DOCX file.
    base_img_dir (str): Base directory to store extracted images.
    
Returns:
    tuple: Extracted text, list of images, and document name.
"""

def process_docx_and_extract_images(docx_path, base_img_dir):
    # Extract the .docx file name (without extension)
    docx_name = os.path.splitext(os.path.basename(docx_path))[0]
    
    # Create a unique directory for the .docx file's images
    unique_img_dir = os.path.join(base_img_dir, docx_name)
    os.makedirs(unique_img_dir, exist_ok=True)
    
    # Extract text and images to the unique directory
    text = docx2txt.process(docx_path, unique_img_dir)
    
    # Return a list of extracted images
    extracted_images = os.listdir(unique_img_dir)
    
    # Return the extracted text and image information
    return text, extracted_images, docx_name

"""
Function: extract_pdf

Extracts text and images from a PDF file.

Args:
    pdf_path (str): Path to the PDF file.
"""

def extract_pdf(pdf_path):
    doc = fitz.open(pdf_path)

    images = []
    pdf_text = ""
    
    for page in doc:
        pdf_text += page.get_text()
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            base64_img = base64.b64encode(image_bytes).decode('utf-8')
            #image_ext = base_image["ext"]
            response = ol.generate(model='llava', prompt=pt1, images=[base64_img])
            summary = f"\nImage Name: {pdf_path}\nDescription: {response['response']}\n\n"
            document = Document(text=summary,metadata={"file_name": pdf_path})
            documents.append(document)

"""
Function: ocr

Performs OCR on a PDF file.

Args:
    file_path (str): Path to the PDF file.
    save_path (str): Path to save the OCR'd PDF.
"""

def ocr(file_path, save_path):
    try:
        ocrmypdf.ocr(file_path, save_path)
    except:
        print("Could not generate OCR.  This often indicates that the PDF was generated from an office document and does not need OCR")


# Base directory for extracted docx images
base_img_dir = './img/'
os.makedirs(base_img_dir, exist_ok=True)

# Load Documents
document_loader = SimpleDirectoryReader(directory_path).load_data()

for file in os.listdir(directory_path):
    if file.endswith(".docx"):
        text, extracted_images, docx_name = process_docx_and_extract_images(directory_path+"/"+file, base_img_dir)

        # Example of generating captions with references to the original .docx file
        for image in extracted_images:
            caption_docx_image_documents(image, docx_name)

    elif file.endswith(".pdf"):
        # Add OCR to PDF files where applicable
        ocr(directory_path+"/"+file, directory_path+file[:-4]+"-ocr.pdf")
        # Extract images from the PDF file
        extract_pdf(directory_path+"/"+file)
        
    elif file.endswith(".png") or file.endswith(".png") or file.endswith(".jpeg"):
        caption_image_file(directory_path+"/"+file)


index = VectorStoreIndex.from_vector_store(vector_store=vector_store)

for doc in documents:
    # Pgvector doesn't allow null bytes.  Make sure to remove them all
    doc.text = doc.text.replace('\x00', '')
    index.insert(doc)

for loaded_doc in document_loader:
    # Pgvector doesn't allow null bytes.  Make sure to remove them all
    loaded_doc.text = loaded_doc.text.replace('\x00', '')
    index.insert(loaded_doc)

