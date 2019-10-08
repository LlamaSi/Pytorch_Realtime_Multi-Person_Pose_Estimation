with open('train2014.json', 'r') as f:
	lines = f.readlines()
with open('train2014_parsing.json', "w+") as g:
	new_lines = lines[0].replace('.jpg', '_gray.png')
	g.writelines(new_lines)