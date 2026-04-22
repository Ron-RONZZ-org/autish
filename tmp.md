# bug fixes

- some random entries crepted into my `encik` entry database. delete them:

 #    UUID        Titolo                           
 1    b343de6d    Fonto [Celo](#c3a1098e)          
 2    a6257b7f    Fonto-ilo_f0 [Celo](#3e95fcd1)   
 3    24faa46d    Fonto-4cd6ae8f [Celo](#f519db34) 
 4    7e870cb6    Fonto-ccf60686 [Celo](#80585972) 
 5    368ecd48    Fonto-e72935d8 [Celo](#c0ae10aa) 
 6    b0956194    Fonto-10c2f717 [Celo](#8a50b858) 
 7    404c451f    Fonto-07569bdf [Celo](#f5187a38) 
 8    7b86baad    Fonto-fe39bf66 [Celo](#7bebf597) 
 9    a70306e4    Fonto-da9b3381 [Celo](#17ca09b2) 
 10   64f67110    Fonto-50a7346f [Celo](#99280a37) 
 11   c6a4e221    Fonto-24a0049f [Celo](#fd96e6e6) 
 12   8dbf98d9    Fonto-2bf2bad6 [Celo](#56cd0d56) 
 13   f49f839a    Fonto-7f726762 [Celo](#86f8e44e) 
 14   aa095cec    Fonto-b51fcbe7 [Celo](#898f5189) 
 15   aa3bcf89    Fonto-5d5cbad3 [Celo](#ee1cdfea) 
 16   e6c950db    Fonto-adc46fb2 [Celo](#ffd1c9be) 
 17   1a941736    Fonto-88312ff4 [Celo](#8f47cedf) 
 18   1e1cea6c    Fonto-36b0d565 [Celo](#b6d76afc) 
 19   b1c969b5    Fonto-67ecc126 [Celo](#d8b5f09d) 
 20   c1233af3    Fonto-87c41531 [Celo](#a35d1427) 

- `verki` is broken:
```
(autish-py3.12) rongzhou@libres:~/kodo/autish$ verki generi -i "Generate .enc on 'ECHO IV'" -K /home/rongzhou/kodo/autish/AI-kuntekstoj/enc-AI-kunteksto.md -E ~/kodo/ronzz-markmap/encik/ECHO-IV.enc -m deepseek-ai/DeepSeek-R1 
Eraro: Hugging Face HTTP-eraro 404: <!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Error</title>
</head>
<body>
<pre>Cannot POST /models/deepseek-ai/DeepSeek-R1</pre>
</body>
</html>
```

Official inference provider examples:

```
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=os.environ["HF_TOKEN"],
)

completion = client.chat.completions.create(
    model="deepseek-ai/DeepSeek-R1:hyperbolic",
    messages=[
        {
            "role": "user",
            "content": "What is the capital of France?"
        }
    ],
)

print(completion.choices[0].message)
```

