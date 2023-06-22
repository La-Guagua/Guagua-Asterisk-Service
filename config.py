from dotenv import dotenv_values
config = dotenv_values(".env")

ARI_SERV = config['ARI_SERV']
ARI_PORT = config['ARI_PORT']
ARI_USER = config['ARI_USER']
ARI_PWD = config['ARI_PWD']
APP_NAME = config['APP_NAME']