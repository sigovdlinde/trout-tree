from flask import Flask, render_template, request, url_for

import matplotlib
matplotlib.use('Agg')  # This needs to be done before importing plt
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

app = Flask(__name__)

# Execute the ancestry query
ancestry_query = """
WITH RECURSIVE ancestry(self_id, parent_id, depth) AS (
  SELECT self_id, left_parent_id, 1 FROM tokens WHERE left_parent_id IS NOT NULL
  UNION ALL
  SELECT self_id, right_parent_id, 1 FROM tokens WHERE right_parent_id IS NOT NULL
  UNION ALL
  SELECT ancestry.self_id, tokens.left_parent_id, ancestry.depth+1 
  FROM ancestry JOIN tokens ON ancestry.parent_id = tokens.self_id
  WHERE tokens.left_parent_id IS NOT NULL
  UNION ALL
  SELECT ancestry.self_id, tokens.right_parent_id, ancestry.depth+1 
  FROM ancestry JOIN tokens ON ancestry.parent_id = tokens.self_id
  WHERE tokens.right_parent_id IS NOT NULL
)
SELECT self_id, COUNT(*) - COUNT(DISTINCT parent_id) AS inbreeding_coefficient
FROM ancestry
GROUP BY self_id
ORDER BY inbreeding_coefficient DESC;
"""

API_URL = "https://api.nftrout.com/trout/23294/"

def get_api_data():
    response = requests.get(API_URL)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def process_api_data(api_data):
    trouts = api_data['result']  # Extract the list of trouts
    processed_data = {trout['id']: trout for trout in trouts}
    print(processed_data)
    return processed_data


def fetch_parent(data, child_id):
    """Fetch the parents of a given trout from the processed API data."""
    trout = data.get(child_id)
    if trout:
        left_parent_id = None
        right_parent_id = None
        if trout.get('parents'):
            parents = trout['parents']
            if len(parents) > 0:
                left_parent_id = parents[0].get('tokenId')  # Assuming first parent is 'left'
            if len(parents) > 1:
                right_parent_id = parents[1].get('tokenId')  # Assuming second parent is 'right'

        return trout['id'], trout['owner'], left_parent_id, right_parent_id
    return None


def build_family_tree(data, trout_id, tree=None, level=0):
    """Recursively build the family tree using the processed API data."""
    if tree is None:
        tree = {}

    trout = fetch_parent(data, trout_id)
    if trout is None:
        return None

    tree[trout[0]] = {'name': trout[1], 'level': level, 'children': {}}

    if trout[2] is not None:  # left parent
        tree[trout[0]]['children']['left'] = build_family_tree(data, trout[2], {}, level + 1)
    if trout[3] is not None:  # right parent
        tree[trout[0]]['children']['right'] = build_family_tree(data, trout[3], {}, level + 1)

    return tree

def add_nodes_edges(graph, node, inbreeding_dict, level=0):
    print(node)
    node_id = node['id']  # Use the ID directly
    inbreeding_coefficient = inbreeding_dict.get(node_id, 0)
    graph.add_node(node_id, level=level, inbreeding=inbreeding_coefficient)
    
    for child_key, child_node in node['children'].items():
        if child_node:
            child_id = child_node['id']
            graph.add_node(child_id, level=level + 1, inbreeding=inbreeding_dict.get(child_id, 0))
            graph.add_edge(node_id, child_id)
            add_nodes_edges(graph, child_node, inbreeding_dict, level + 1)

def fetch_direct_descendants(data, parent_id):
    """Fetch the direct descendants of a given trout."""
    descendants = []
    for id, trout in data.items():
        if trout.get('parents') and parent_id in [p['tokenId'] for p in trout['parents']]:
            descendants.append((id, trout['owner']))  # Assuming 'owner' is a relevant field
    return descendants


def build_full_descendant_tree(data, trout_id):
    """Recursively build the full descendant tree of a given trout."""
    descendants = {}
    direct_descendants = fetch_direct_descendants(data, trout_id)

    for descendant_id, owner in direct_descendants:
        # Recursive call to build the descendant subtree
        descendants[descendant_id] = build_full_descendant_tree(data, descendant_id)

    return descendants

def add_descendants_to_graph(graph, parent_id, descendants, inbreeding_dict):
    for child_id, grandchildren in descendants.items():
        inbreeding_coefficient = inbreeding_dict.get(child_id, 0)  # Use 0 if not found
        graph.add_node(child_id, label=f'Trout #{child_id}', inbreeding=inbreeding_coefficient)
        graph.add_edge(parent_id, child_id)
        add_descendants_to_graph(graph, child_id, grandchildren, inbreeding_dict)


# Define a color map with a lighter green and red gradient
def get_color(inbreeding_coefficient):
    # Normalize the inbreeding coefficient to be between 0 and 1
    normalized_coefficient = inbreeding_coefficient / 1000.0
    # Create a red-light green colormap
    color = mcolors.LinearSegmentedColormap.from_list("", ["#4bbf4b","red"])  # lighter green
    # Return the corresponding color for the normalized coefficient
    return color(normalized_coefficient)

@app.route('/', methods=['GET', 'POST'])
def index():
    api_data = get_api_data()
    if api_data is None:
        return "Error fetching data from API", 500

    processed_data = process_api_data(api_data)

    trout_id = None
    family_tree_image = None
    # Set a default value for tree_type in case it's not in the form data
    tree_type = request.form.get('tree_type', 'full_tree')

    if request.method == 'POST':
        trout_id = request.form.get('trout_id')
        tree_type = request.form.get('tree_type', 'full_tree')
        show_images = request.form.get('show_images')

        # Connect to the SQLite database
        # conn = sqlite3.connect('nftrout.sqlite')

        # Fetch the inbreeding coefficients
        # inbreeding_dict = {row[0]: row[1] for row in conn.execute(ancestry_query)}
        inbreeding_dict = {}

        # Create a networkx graph
        G = nx.DiGraph()

        # Depending on the type of tree requested, build the appropriate tree
        if tree_type == 'ancestors':
            # Call your existing function to build the family tree
            family_tree = build_family_tree(processed_data, int(trout_id))
            add_nodes_edges(G, family_tree[int(trout_id)], inbreeding_dict)
        elif tree_type == 'descendants':
            # Build the full descendant tree for the given trout
            descendant_tree = build_full_descendant_tree(processed_data, int(trout_id))
            add_descendants_to_graph(G, int(trout_id), descendant_tree, inbreeding_dict)
        elif tree_type == 'full_tree':
            # Combine both ancestors and descendants into the full tree
            family_tree = build_family_tree(processed_data, int(trout_id))
            add_nodes_edges(G, family_tree[int(trout_id)], inbreeding_dict)
            descendant_tree = build_full_descendant_tree(processed_data, int(trout_id))
            add_descendants_to_graph(G, int(trout_id), descendant_tree, inbreeding_dict)

        # Close the database connection
        # conn.close()

        if show_images:

            # Draw the graph
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
                
                # Do not resize to thumbnail, use the original size, or resize to a size that maintains quality
                desired_size = (size_x, size_y)  # Adjust as needed based on the original image size
                img = img.resize(desired_size, Image.Resampling.LANCZOS)
                
                xi, yi = pos[node]
                rgba_color = get_color(G.nodes[node].get('inbreeding', 0))

                # Adjust zoom factor to match the image size
                zoom_factor = desired_size[0] / img.size[0]

                xi, yi = pos[node]
                rgba_color = get_color(G.nodes[node].get('inbreeding', 0))
                border_size = 100
                border_rect = Rectangle((xi - border_size / 2, yi - border_size / 3),
                                        border_size, border_size / 3, linewidth=2,
                                        edgecolor=rgba_color, facecolor='none', zorder=0)
                # ax.add_patch(border_rect)

                im = OffsetImage(img, zoom=zoom_factor)
                ab = AnnotationBbox(im, (xi, yi), xycoords='data', frameon=False, zorder=1)
                ax.add_artist(ab)
                ax.text(xi, yi + 8, f'#{node}', ha='center', va='bottom', zorder=2, color='black', fontsize=20)
            
            plt.axis('off')

            # Save the plot to a file
            plot_filename = 'family_tree.png'
            plt.savefig(f'./static/{plot_filename}', dpi=300)
            plt.close()

            # Pass the filename of the plot to the template
            return render_template('index.html', family_tree_image=url_for('static', filename=plot_filename))

        else:

            # Use the Graphviz layout to position the nodes
            pos = graphviz_layout(G, prog='dot', args='-Grankdir=TB')

            # Get node colors based on the inbreeding coefficient
            node_colors = [get_color(G.nodes[node].get('inbreeding', 0)) for node in G.nodes()]

            # Draw the graph
            node_count = len(G.nodes)
            if node_count < 30:
                figsize = (12, 12)
            elif node_count < 50:
                figsize = (20, 20)
            else:
                figsize = (30, 30)

            # Use the dynamic size for the figure
            plt.figure(figsize=figsize)
            nx.draw(G, pos, with_labels=True, node_size=1500, node_color=node_colors, font_size=10, arrows=True)

            # Save the plot to a file
            plt.savefig('static/family_tree.png')
            plt.close()

            return render_template('index.html', family_tree_image='static/family_tree.png')


    # Initial or non-POST request
    return render_template('index.html', family_tree_image=None, data=processed_data)


if __name__ == '__main__':
    app.run(debug=True, threaded=False)
