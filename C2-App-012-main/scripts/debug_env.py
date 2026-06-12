from dotenv import load_dotenv
import os
load_dotenv()
print('AI_LOG_SERVER=' + str(os.environ.get('AI_LOG_SERVER')))
print('AI_LOG_API_KEY=' + str(os.environ.get('AI_LOG_API_KEY')))
print('AI_LOG_DIR=' + str(os.environ.get('AI_LOG_DIR')))
