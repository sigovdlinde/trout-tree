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

# This is your existing function to build a family tree, unchanged
def fetch_parent(conn, child_id):
    """Fetch the parents of a given trout."""
    query = """
    SELECT id, name, left_parent_id, right_parent_id
    FROM tokens
    WHERE id = ?
    """
    parent = conn.execute(query, (child_id,)).fetchone()
    return parent

def build_family_tree(conn, trout_id, tree=None, level=0):
    """Recursively build the family tree."""
    if tree is None:
        tree = {}

    trout = fetch_parent(conn, trout_id)
    if trout is None:
        return None

    # Add trout to the tree
    tree[trout[0]] = {'name': trout[1], 'level': level, 'children': {}}

    # Recursively add parents if they exist
    if trout[2] is not None:  # left parent
        tree[trout[0]]['children']['left'] = build_family_tree(conn, trout[2], {}, level + 1)
    if trout[3] is not None:  # right parent
        tree[trout[0]]['children']['right'] = build_family_tree(conn, trout[3], {}, level + 1)

    return tree

def add_nodes_edges(graph, node, inbreeding_dict, level=0):
    node_name = node['name'].split('#')[-1].strip()
    inbreeding_coefficient = inbreeding_dict.get(int(node_name), 0)
    graph.add_node(node_name, level=level, inbreeding=inbreeding_coefficient)
    
    for child_id, child_node in node['children'].items():
        if child_node:
            # Now do the same for the child nodes
            for actual_child_id, actual_child in child_node.items():
                if actual_child:
                    child_name = actual_child['name'].split('#')[-1].strip()
                    graph.add_node(child_name, level=level+1, inbreeding=inbreeding_dict.get(int(child_name), 0))
                    graph.add_edge(child_name, node_name)
                    # Pass inbreeding_dict properly here
                    add_nodes_edges(graph, actual_child, inbreeding_dict, level + 1)

def fetch_direct_descendants(conn, parent_id):
    """Fetch the direct descendants of a given trout."""
    query = """
    SELECT id, name
    FROM tokens
    WHERE left_parent_id = ? OR right_parent_id = ?
    """
    descendants = conn.execute(query, (parent_id, parent_id)).fetchall()
    return descendants


def build_full_descendant_tree(conn, trout_id):
    """Recursively build the full descendant tree of a given trout."""
    descendants = {}
    direct_descendants = fetch_direct_descendants(conn, trout_id)

    for descendant_id, name in direct_descendants:
        # Recursive call to build the descendant subtree
        descendants[descendant_id] = build_full_descendant_tree(conn, descendant_id)

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
    normalized_coefficient = inbreeding_coefficient / 100.0
    # Create a red-light green colormap
    color = mcolors.LinearSegmentedColormap.from_list("", ["#4bbf4b","red"])  # lighter green
    # Return the corresponding color for the normalized coefficient
    return color(normalized_coefficient)

@app.route('/', methods=['GET', 'POST'])
def index():
    trout_id = None
    family_tree_image = None
    # Set a default value for tree_type in case it's not in the form data
    tree_type = request.form.get('tree_type', 'ancestors')

    if request.method == 'POST':
        trout_id = request.form.get('trout_id')
        tree_type = request.form['tree_type']
        show_images = 'show_images' in request.form

        # Connect to the SQLite database
        conn = sqlite3.connect('nftrout.sqlite')

        # Fetch the inbreeding coefficients
        inbreeding_dict = {row[0]: row[1] for row in conn.execute(ancestry_query)}

        # Create a networkx graph
        G = nx.DiGraph()

        # Depending on the type of tree requested, build the appropriate tree
        if tree_type == 'ancestors':
            # Call your existing function to build the family tree
            family_tree = build_family_tree(conn, int(trout_id))
            add_nodes_edges(G, family_tree[int(trout_id)], inbreeding_dict)
        elif tree_type == 'descendants':
            # Build the full descendant tree for the given trout
            descendant_tree = build_full_descendant_tree(conn, int(trout_id))
            add_descendants_to_graph(G, int(trout_id), descendant_tree, inbreeding_dict)

        # Close the database connection
        conn.close()

        if show_images:

            # Now draw the graph using the new method
            fig, ax = plt.subplots(figsize=(50, 50))
            pos = graphviz_layout(G, prog='dot', args='-Grankdir=TB')
            nx.draw_networkx_edges(G, pos, arrows=True)
            
            for node in G.nodes():
                image_path = f'./static/trouts/trout_{node}.png'
                img = Image.open(image_path)
                
                # Do not resize to thumbnail, use the original size, or resize to a size that maintains quality
                desired_size = (200, 200)  # Adjust as needed based on the original image size
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
                ax.add_patch(border_rect)

                im = OffsetImage(img, zoom=zoom_factor)
                ab = AnnotationBbox(im, (xi, yi), xycoords='data', frameon=False, zorder=1)
                ax.add_artist(ab)
                ax.text(xi, yi + border_size / 4 + 2, f'#{node}', ha='center', va='bottom', zorder=2, color='black', fontsize=20)
            
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
    return render_template('index.html', family_tree_image=None)


if __name__ == '__main__':
    app.run(debug=True, threaded=False)
