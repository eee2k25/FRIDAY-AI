import re, os
repo='C:\\MARVEL\\FRIDAY'
path=os.path.join(repo,'friday.py')
content=open(path).read()
new_content=re.sub(r'API_KEY = ".*"', 'API_KEY = "YOUR_GROQ_API_KEY"', content)
open(path,'w',encoding='utf-8').write(new_content)
print('Replaced')