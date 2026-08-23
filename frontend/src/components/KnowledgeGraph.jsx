import React, { useEffect, useRef } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom } from "d3-zoom";
import { colorVarForType } from "../lib/entityStyle";
import useGraphData from "../hooks/useGraphData";

const R_CENTER = 26;
const R_HOP1 = 16;
const R_HOP2 = 10;

const LEGEND = [
  { label: "Person", varName: "--c-person" },
  { label: "Place", varName: "--c-place" },
  { label: "Civilization", varName: "--c-civ" },
  { label: "Polity", varName: "--c-polity" },
  { label: "Document", varName: "--c-doc" },
  { label: "Concept", varName: "--c-concept" },
];

function radiusFor(node, centerId) {
  if (node.id === centerId) return R_CENTER;
  return node.__hop === 2 ? R_HOP2 : R_HOP1;
}

// A real force-directed layout (d3-force physics + d3-drag + d3-zoom),
// still rendered as hand-written SVG like the rest of the app — no canvas,
// no graph-viz framework. D3 owns node positions and DOM updates inside
// the simulation's tick loop (imperative, for performance at ~60 nodes);
// React only owns mount/unmount of the SVG and the data feeding it.
//
// Deliberately does NOT trigger generateEntityImage for any node — only
// EntityDetail's Portrait does that, for the one currently-selected
// entity. Rendering ~60 graph nodes must never fan out into ~60
// simultaneous image-generation requests. Nodes here only ever show a
// portrait that's already cached (entity.image_url already on the doc).
export default function KnowledgeGraph({ entity, neighbors, onSelectEntity }) {
  const { nodes: rawNodes, links: rawLinks } = useGraphData(entity, neighbors);
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const onSelectRef = useRef(onSelectEntity);
  onSelectRef.current = onSelectEntity;

  useEffect(() => {
    if (!entity || rawNodes.length === 0 || !svgRef.current || !containerRef.current) return;

    const width = containerRef.current.clientWidth || 800;
    const height = containerRef.current.clientHeight || 420;

    const hopOf = new Map([[entity.id, 0]]);
    for (const { entity: n } of neighbors) hopOf.set(n.id, 1);
    const nodes = rawNodes.map((n) => ({ ...n, __hop: hopOf.get(n.id) ?? 2 }));
    const links = rawLinks.map((l) => ({ ...l }));

    const svg = select(svgRef.current);
    svg.selectAll("*").remove();
    const zoomLayer = svg.append("g").attr("class", "kg-zoom-layer");

    const linkSel = zoomLayer
      .append("g")
      .attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => (d.hop === 2 ? "#2c313c" : "#4a5568"))
      .attr("stroke-width", (d) => (d.hop === 2 ? 1 : 1.6));

    const linkLabelSel = zoomLayer
      .append("g")
      .selectAll("text")
      .data(links.filter((l) => l.type))
      .join("text")
      .attr("class", "kg-link-label")
      .text((d) => d.type.toLowerCase().replaceAll("_", " "));

    const nodeSel = zoomLayer
      .append("g")
      .selectAll("g")
      .data(nodes, (d) => d.id)
      .join("g")
      .attr("class", "kg-node")
      .on("click", (event, d) => onSelectRef.current(d.id));

    nodeSel
      .append("circle")
      .attr("r", (d) => radiusFor(d, entity.id))
      .attr("fill", (d) => `var(${colorVarForType(d.entity_type)})`)
      .attr("stroke", (d) => (d.id === entity.id ? "var(--accent)" : "var(--bg-raised)"))
      .attr("stroke-width", (d) => (d.id === entity.id ? 3 : 2));

    // Layer a cached portrait on top of the color circle when one already
    // exists — never triggers generation, see the note above the component.
    nodeSel.each(function (d) {
      if (!d.image_url) return;
      const r = radiusFor(d, entity.id);
      const g = select(this);
      const clipId = `kg-clip-${d.id}`;
      g.append("clipPath").attr("id", clipId).append("circle").attr("r", r);
      g.append("image")
        .attr("href", d.image_url)
        .attr("x", -r)
        .attr("y", -r)
        .attr("width", r * 2)
        .attr("height", r * 2)
        .attr("preserveAspectRatio", "xMidYMid slice")
        .attr("clip-path", `url(#${clipId})`)
        .style("pointer-events", "none");
    });

    nodeSel
      .append("text")
      .attr("class", "kg-node-label")
      .attr("y", (d) => radiusFor(d, entity.id) + 12)
      .text((d) => d.canonical_name);

    const simulation = forceSimulation(nodes)
      .force(
        "link",
        forceLink(links)
          .id((d) => d.id)
          .distance((d) => (d.hop === 2 ? 55 : 95))
          .strength(0.5)
      )
      .force("charge", forceManyBody().strength(-220))
      .force("center", forceCenter(width / 2, height / 2))
      .force(
        "collide",
        forceCollide((d) => radiusFor(d, entity.id) + 16)
      );

    function render() {
      linkSel
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      linkLabelSel.attr("x", (d) => (d.source.x + d.target.x) / 2).attr("y", (d) => (d.source.y + d.target.y) / 2);
      nodeSel.attr("transform", (d) => `translate(${d.x},${d.y})`);
    }

    // Settle the layout synchronously before the first paint (cheap at
    // this size — well under a frame) instead of only relying on the
    // timer-driven tick loop: the graph looks right immediately rather
    // than animating in from a jumbled starting scatter. The timer
    // (attached right after) keeps running for drag interactions.
    simulation.stop();
    for (let i = 0; i < 150; i++) simulation.tick();
    render();
    simulation.restart();
    simulation.on("tick", render);

    nodeSel.call(
      d3drag()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.25).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on("drag", (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        })
    );

    svg.call(
      d3zoom()
        .scaleExtent([0.4, 2.5])
        .on("zoom", (event) => zoomLayer.attr("transform", event.transform))
    );

    return () => {
      simulation.stop();
      svg.selectAll("*").remove();
    };
  }, [entity, rawNodes, rawLinks, neighbors]);

  if (!entity) {
    return <div className="empty-note">Select an entity to see its connections graphed here.</div>;
  }

  return (
    <>
      <div ref={containerRef} className="kg-canvas">
        <svg ref={svgRef} width="100%" height="100%" />
      </div>
      <div className="kg-legend">
        {LEGEND.map((l) => (
          <div className="legend-item" key={l.label}>
            <span className="legend-dot" style={{ background: `var(${l.varName})` }} />
            {l.label}
          </div>
        ))}
      </div>
    </>
  );
}
