from flask import Flask, render_template, request, url_for

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.patches import Rectangle

from PIL import Image
import networkx as nx
from networkx.drawing.nx_agraph import graphviz_layout

import sqlite3
import os

import requests

import cairosvg

app = Flask(__name__)

def get_api_data():
    response = requests.get('https://api.nftrout.com/trout/23294/')
    if response.status_code == 200:
        return response.json()
    else:
        return None

def process_api_data(api_data):
    trouts = api_data['result']
    processed_data = {trout['id']: trout for trout in trouts}
    return processed_data

def get_latest_trout_number(api_url):
    response = requests.get(api_url)
    if response.status_code == 200:
        data = response.json()
        latest_trout_number = data['result'][-1]['id']
        return latest_trout_number
    else:
        raise Exception("Could not fetch the latest trout number from the API")

def generate_trout_image_url(trout_number):
    return f'https://api.nftrout.com/trout/23294/{trout_number}/image.svg'

def download_and_convert_trout_images(directory='./static/trouts'):
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    latest_trout_number = get_latest_trout_number("https://api.nftrout.com/trout/23294/")
    existing_images = {file.split('_')[1].split('.')[0] for file in os.listdir(directory) if file.endswith('.png')}
    
    for trout_number in range(1, latest_trout_number + 1):
        trout_str = str(trout_number)
        
        if trout_str in existing_images:
            continue
        
        url = generate_trout_image_url(trout_number)
        response = requests.get(url)
        
        if response.status_code == 200:
            svg_file_path = os.path.join(directory, f'trout_{trout_number}.svg')
            png_file_path = os.path.join(directory, f'trout_{trout_number}.png')
            
            with open(svg_file_path, 'wb') as file:
                file.write(response.content)
            
            cairosvg.svg2png(url=svg_file_path, write_to=png_file_path)
            print(trout_number)
            
            os.remove(svg_file_path)
        else:
            print(f"Failed to download image for trout #{trout_number}")
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")


def fetch_parent(data, child_id):
    trout = data.get(child_id)
    if trout:
        left_parent_id = trout.get('parents', [{}])[0].get('tokenId') if trout.get('parents') else None
        right_parent_id = trout.get('parents', [{}])[1].get('tokenId') if trout.get('parents') and len(trout.get('parents')) > 1 else None
        return trout['id'], trout['coi'], left_parent_id, right_parent_id
    else:
        print(f"Trout with ID {child_id} not found in data")
        return None

def build_family_tree(data, trout_id, tree=None, level=0):
    if tree is None:
        tree = {}

    trout_info = fetch_parent(data, trout_id)
    if trout_info is None:
        return None

    tree[trout_info[0]] = {'id': trout_info[0], 'coi': trout_info[1], 'level': level, 'children': {}}

    left_parent_id = trout_info[2]
    right_parent_id = trout_info[3]
    if left_parent_id:
        tree[trout_info[0]]['children']['left'] = build_family_tree(data, left_parent_id, {}, level + 1)
    if right_parent_id:
        tree[trout_info[0]]['children']['right'] = build_family_tree(data, right_parent_id, {}, level + 1)

    return tree

def add_nodes_edges(graph, node, level=0):
    node_id = node['id']
    graph.add_node(node_id, level=level, inbreeding=node['coi'])
    
    for side in ['left', 'right']:
        parent_side = node['children'].get(side)
        if parent_side:
            for parent_id, parent_data in parent_side.items():
                if parent_data:
                    graph.add_node(parent_id, level=level - 1, inbreeding=parent_data['coi'])
                    graph.add_edge(parent_id, node_id)  # Reverse the order to parent -> child
                    add_nodes_edges(graph, parent_data, level - 1)

def fetch_direct_descendants(data, parent_id):
    """Fetch the direct descendants of a given trout."""
    descendants = []
    for id, trout in data.items():
        if trout.get('parents') and parent_id in [p['tokenId'] for p in trout['parents']]:
            descendants.append({'id': id, 'coi': trout['coi']})
    return descendants

def build_full_descendant_tree(data, trout_id):
    """Recursively build the full descendant tree of a given trout."""
    descendant_tree = {}
    direct_descendants = fetch_direct_descendants(data, trout_id)

    for descendant in direct_descendants:
        descendant_id = descendant['id']
        descendant_coi = descendant['coi']
        # Recursive call to build the descendant subtree
        descendant_tree[descendant_id] = {'coi': descendant_coi, 'descendants': build_full_descendant_tree(data, descendant_id)}

    return descendant_tree

def add_descendants_to_graph(graph, parent_id, descendant_tree):
    for child_id, child_info in descendant_tree.items():
        coi = child_info['coi']
        graph.add_node(child_id, label=f'Trout #{child_id}', inbreeding=coi)
        graph.add_edge(parent_id, child_id)
        # Recursively add descendants if there are any
        if child_info['descendants']:  # Check if there are further descendants
            add_descendants_to_graph(graph, child_id, child_info['descendants'])

# Define a color map with a lighter green and red gradient
def get_color(inbreeding_coefficient):
    color = mcolors.LinearSegmentedColormap.from_list("", ["#4bbf4b","red"])  # lighter green
    return color(inbreeding_coefficient)

@app.route('/', methods=['GET', 'POST'])
def index():
    api_data = get_api_data()
    if api_data is None:
        return "Error fetching data from API", 500
    processed_data = process_api_data(api_data)

    trout_id = None
    family_tree_image = None

    tree_type = request.form.get('tree_type', 'full_tree')
    if request.method == 'POST':
        trout_id = request.form.get('trout_id')
        tree_type = request.form.get('tree_type', 'full_tree')
        # show_images = request.form.get('show_images')

            #         <label for="show_images">Show Images:</label>
            # <input type="checkbox" id="show_images" name="show_images" value="true">
        
        show_images = False

        G = nx.DiGraph()

        # Depending on the type of tree requested, build the appropriate tree
        if tree_type == 'ancestors':
            family_tree = build_family_tree(processed_data, int(trout_id))
            add_nodes_edges(G, family_tree[int(trout_id)])
        elif tree_type == 'descendants':
            descendant_tree = build_full_descendant_tree(processed_data, int(trout_id))
            add_descendants_to_graph(G, int(trout_id), descendant_tree)
        elif tree_type == 'full_tree':
            family_tree = build_family_tree(processed_data, int(trout_id))
            add_nodes_edges(G, family_tree[int(trout_id)])
            descendant_tree = build_full_descendant_tree(processed_data, int(trout_id))
            add_descendants_to_graph(G, int(trout_id), descendant_tree)

        if show_images:

            # Update trout images.
            download_and_convert_trout_images()

            node_count = len(G.nodes)
            if node_count < 15:
                figsize = (20, 20)
                size_x = 218
                size_y = 133
            else:
                figsize = (30, 30)
                size_x = 109
                size_y = 66
            # Now draw the graph using the new method
            fig, ax = plt.subplots(figsize=figsize)
            pos = graphviz_layout(G, prog='dot', args='-Grankdir=TB')
            nx.draw_networkx_edges(G, pos, arrows=True)
            
            for node in G.nodes():
                image_path = f'./static/trouts/trout_{node}.png'
                img = Image.open(image_path)
                
                desired_size = (size_x, size_y)
                img = img.resize(desired_size, Image.Resampling.LANCZOS)
                
                xi, yi = pos[node]
                rgba_color = get_color(G.nodes[node].get('inbreeding', 0))
                # Adjust zoom factor to match the image size
                zoom_factor = desired_size[0] / img.size[0]
                xi, yi = pos[node]
                rgba_color = get_color(G.nodes[node].get('inbreeding', 0))

                im = OffsetImage(img, zoom=zoom_factor)
                ab = AnnotationBbox(im, (xi, yi), xycoords='data', frameon=False, zorder=1)
                ax.add_artist(ab)
                ax.text(xi, yi + 8, f'#{node}', ha='center', va='bottom', zorder=2, color='black', fontsize=20)
            
            plt.axis('off')
            plot_filename = 'family_tree.png'
            plt.savefig(f'./static/{plot_filename}', dpi=300)
            plt.close()
            return render_template('index.html', family_tree_image=url_for('static', filename=plot_filename))
        else:
            pos = graphviz_layout(G, prog='dot', args='-Grankdir=TB')
            node_colors = [get_color(G.nodes[node].get('inbreeding', 0)) for node in G.nodes()]
            node_count = len(G.nodes)

            if node_count < 30:
                figsize = (12, 12)
            elif node_count < 50:
                figsize = (20, 20)
            else:
                figsize = (30, 30)

            plt.figure(figsize=figsize)
            nx.draw(G, pos, with_labels=True, node_size=1500, node_color=node_colors, font_size=10, arrows=True)

            plt.savefig('static/family_tree.png')
            plt.close()
            return render_template('index.html', family_tree_image='static/family_tree.png')

    # Initial or non-POST request
    return render_template('index.html', family_tree_image=None, data=processed_data)

@app.route('/statistics')
def statistics():
    api_data = get_api_data()
    processed_data = process_api_data(api_data)

    return render_template('statistics.html')

if __name__ == '__main__':
    app.run(debug=True, threaded=False)
