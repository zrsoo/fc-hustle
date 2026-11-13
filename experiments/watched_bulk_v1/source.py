"""Decode EA public string constants statically; never execute downloaded JS."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import re


def decode_table(text):
    encoded=ast.literal_eval(re.search(r'var a0_0x26ce=(\[.*?\]);',text).group(1))
    table=[]
    trans=str.maketrans('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/','ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/')
    for v in encoded:
        s=v.translate(trans)
        table.append(base64.b64decode(s+'='*((-len(s))%4)).decode('utf8'))
    def val(rotation,index):
        s=table[(rotation+index-0x1db)%len(table)]
        match=re.match(r'^\s*([+-]?\d+)',s)
        if not match:
            raise ValueError('not_numeric')
        return int(match.group(1))
    rotations=[]
    for r in range(len(table)):
        try:
            n=lambda i:val(r,i)
            result=-n(0xd51)*n(0x1179)+n(0x8e4)-n(0x14be)-n(0x108b)-n(0xe7d)*n(0x62d)+n(0x2e1)*n(0x11f8)-n(0x45d)*n(0x79c)
            if result==0x98965:
                rotations.append(r)
        except ValueError:
            pass
    if len(rotations)!=1:
        raise ValueError('rotation_not_unique')
    r=rotations[0]
    return lambda i:table[(r+i-0x1db)%len(table)]


def decoded_source(text,decode):
    return re.sub(r'(?:a0_0x[0-9a-f]+|_0x[0-9a-f]+)\((0x[0-9a-f]+)\)',lambda m:json.dumps(decode(int(m.group(1),16))),text)


if __name__=='__main__':
    root=Path('docs/research/001c/001c-03')
    path=Path('private-captures/001c-03-public-source/ocompiled.js')
    raw=path.read_bytes();text=raw.decode('utf8');decode=decode_table(text)
    live=json.loads((root/'inspect-2.json').read_text())
    sources=[]
    for s in live['sources']:
        if s['source'] not in text:
            raise ValueError('public_source_does_not_match_loaded_function')
        sources.append({'owner':s['owner'],'name':s['name'],'loaded_function_sha256':s['sha256'],
                        'source':decoded_source(s['source'],decode)})
    target=root/'native-source-decoded.json'
    with target.open('x') as f:
        json.dump({'url':'https://www.ea.com/ea-sports-fc/ultimate-team/web-app/js/ocompiled.js',
                   'sha256':hashlib.sha256(raw).hexdigest(),'algorithm':'static_custom_base64_and_unique_rotation_checksum_no_JS_execution',
                   'loaded_function_match':True,'sources':sources},f,indent=2)
    print('\n'.join(s['name']+': '+s['source'] for s in sources))
