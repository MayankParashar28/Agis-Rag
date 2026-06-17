import os
import re

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Find elements with bg-primary and text-foreground and replace text-foreground with text-background
    # Since classNames can be in any order, we can use a regex that looks for className="..." containing both
    
    def replacer(match):
        cls_content = match.group(1)
        if 'bg-primary' in cls_content and 'text-foreground' in cls_content:
            # only if it's a solid bg-primary, not bg-primary/10 or text-primary
            # actually, if it's bg-primary/10, text-foreground might be correct.
            # let's only replace if it's strictly "bg-primary" or "bg-primary " or " bg-primary"
            if re.search(r'\bbg-primary\b', cls_content):
                # Check it's not bg-primary/xx
                if not re.search(r'\bbg-primary/[0-9]+', cls_content):
                    cls_content = cls_content.replace('text-foreground', 'text-background')
        return 'className="' + cls_content + '"'

    new_content = re.sub(r'className="([^"]+)"', replacer, content)

    # Let's also handle conditional classes like className={`...`}
    def replacer2(match):
        cls_content = match.group(1)
        if re.search(r'\bbg-primary\b', cls_content) and not re.search(r'\bbg-primary/[0-9]+', cls_content):
            cls_content = cls_content.replace('text-foreground', 'text-background')
        return 'className={`' + cls_content + '`}'
        
    new_content = re.sub(r'className={`([^`]+)`}', replacer2, new_content)
    
    # Let's also handle className={"..."}
    def replacer3(match):
        cls_content = match.group(1)
        if re.search(r'\bbg-primary\b', cls_content) and not re.search(r'\bbg-primary/[0-9]+', cls_content):
            cls_content = cls_content.replace('text-foreground', 'text-background')
        return 'className={"' + cls_content + '"}'
        
    new_content = re.sub(r'className=\{"([^"]+)"\}', replacer3, new_content)

    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, dirs, files in os.walk('/Users/mayankparashar/Downloads/enterprise-rag/frontend/src'):
    for file in files:
        if file.endswith('.tsx'):
            process_file(os.path.join(root, file))

