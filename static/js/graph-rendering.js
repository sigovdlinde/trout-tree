function renderGraph(treeData, showImages) {
    const width = 800;  // Width of the graph
    const height = 600; // Height of the graph

    // Create the SVG container
    const svg = d3.select("#graph-container").append("svg")
        .attr("width", width)
        .attr("height", height);

    // Create a simulation for positioning nodes
    const simulation = d3.forceSimulation(treeData.nodes)
        .force("link", d3.forceLink(treeData.edges).id(d => d.id))
        .force("charge", d3.forceManyBody())
        .force("center", d3.forceCenter(width / 2, height / 2));

    // Create the links (lines)
    const link = svg.append("g")
        .selectAll("line")
        .data(treeData.edges)
        .enter().append("line")
        .style("stroke", "#aaa");

    // Create the nodes (circles)
    const node = svg.append("g")
        .selectAll("circle")
        .data(treeData.nodes)
        .enter().append("circle")
        .attr("r", 5)  // Radius of circle
        .style("fill", "#69b3a2");

    // Add drag behavior to nodes
    node.call(d3.drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended));

    // Add node labels
    const labels = svg.append("g")
        .attr("class", "labels")
        .selectAll("text")
        .data(treeData.nodes)
        .enter().append("text")
        .attr("dx", 12)
        .attr("dy", ".35em")
        .text(d => d.id);

    // Update positions after each simulation tick
    simulation.on("tick", () => {
        link.attr("x1", d => d.source.x)
            .attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x)
            .attr("y2", d => d.target.y);

        node.attr("cx", d => d.x)
            .attr("cy", d => d.y);

        labels.attr("x", d => d.x)
              .attr("y", d => d.y);
    });

    // Drag functions
    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
}
