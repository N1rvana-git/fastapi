with open("src/feishu/router.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "请用一两句话简短总结" in line:
        lines[i] = '                        summary_prompt = f"请用一两句话简短总结以下搜到的价格情报，告诉用户外面的价格是多少，并说一句我们平台的价格更香：\\n{market_data}"\n'
        # remove next row if it has the closing `{market_data}"`
        if '{market_data}"' in lines[i+1]:
            lines.pop(i+1)
        break

with open("src/feishu/router.py", "w") as f:
    f.writelines(lines)
