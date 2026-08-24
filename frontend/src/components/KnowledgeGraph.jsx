import React, { useEffect, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, forceRadial } from "d3-force";
import { select } from "d3-selection";
import { drag as d3drag } from "d3-drag";
import { zoom as d3zoom } from "d3-zoom";
import { colorVarForType } from "../lib/entityStyle";
import useGraphData from "../hooks/useGraphData";

const R_CENTER = 26;
const R_HOP1 = 16;
const R_HOP2 = 10;

// Concentric rings by hop — the single biggest declutter for a busy
// neighborhood: without this, forceManyBody's repulsion alone still lets
// distant nodes drift anywhere, which is what produced the tangled mess in
// the reported screenshot. Radius/strength only, center node untouched.
const RING_RADIUS = { 1: 150, 2: 280 };
const RING_STRENGTH = { 1: 0.25, 2: 0.35 };

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
  const [expanded, setExpanded] = useState(false);
  const { nodes: rawNodes, links: rawLinks } = useGraphData(entity, neighbors, expanded);
  const containerRef = useRef(null);
  const svgRef = useRef(null);
  const onSelectRef = useRef(onSelectEntity);
  onSelectRef.current = onSelectEntity;

  // A fresh entity starts collapsed again — expanding one busy node
  // shouldn't carry over and instantly tangle the next one you look at.
  useEffect(() => {
    setExpanded(false);
  }, [entity?.id]);

  useEffect(() => {
    if (!entity || rawNodes.length === 0 || !svgRef.current || !containerRef.current) return;

    const width = containerRef.current.clientWidth || 800;
    const height = containerRef.current.clientHeight || 420;
    const cx = width / 2;
    const cy = height / 2;

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

    // Invisible wide hit-area on top of each thin visible line — makes
    // hovering to reveal a relationship label actually feasible, a 1.6px
    // stroke is too thin a target otherwise.
    const linkHitSel = zoomLayer
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "transparent")
      .attr("stroke-width", 14)
      .style("cursor", (d) => (d.type ? "help" : "default"));

    const linkLabelSel = zoomLayer
      .append("g")
      .selectAll("text")
      .data(links.filter((l) => l.type))
      .join("text")
      .attr("class", "kg-link-label")
      .text((d) => d.type.toLowerCase().replaceAll("_", " "));

    linkHitSel
      .on("mouseenter", (event, d) => {
        if (!d.type) return;
        linkLabelSel.filter((ld) => ld === d).classed("kg-link-label-visible", true);
      })
      .on("mouseleave", (event, d) => {
        if (!d.type) return;
        linkLabelSel.filter((ld) => ld === d).classed("kg-link-label-visible", false);
      });

    const nodeSel = zoomLayer
      .append("g")
      .selectAll("g")
      .data(nodes, (d) => d.id)
      .join("g")
      .attr("class", (d) => `kg-node${d.__hop === 2 ? " kg-node-hop2" : ""}`)
      .on("click", (event, d) => onSelectRef.current(d.id))
      .on("mouseenter", function () {
        select(this).classed("kg-node-hovered", true);
      })
      .on("mouseleave", function () {
        select(this).classed("kg-node-hovered", false);
      });

    nodeSel
      .append("circle")
      .attr("r", (d) => radiusFor(d, entity.id))
      .attr("fill", (d) => `var(${colorVarForType(d.entity_type)})`)
      .attr("stroke", (d) => (d.id === entity.id ? "var(--accent)" : "var(--bg-raised)"))
      .attr("stroke-width", (d) => (d.id === entity.id ? 3 : 2))
      .attr("opacity", (d) => (d.__hop === 2 ? 0.7 : 1));

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
        .attr("opacity", d.__hop === 2 ? 0.7 : 1)
        .style("pointer-events", "none");
    });

    nodeSel
      .append("text")
      .attr("class", (d) => `kg-node-label${d.__hop === 2 ? " kg-node-label-hop2" : ""}`)
      .attr("y", (d) => radiusFor(d, entity.id) + 12)
      .text((d) => d.canonical_name);

    const simulation = forceSimulation(nodes)
      .force(
        "link",
        forceLink(links)
          .id((d) => d.id)
          .distance((d) => (d.hop === 2 ? 90 : 130))
          .strength(0.35)
      )
      .force("charge", forceManyBody().strength((d) => (d.__hop === 2 ? -140 : -320)))
      .force("center", forceCenter(cx, cy))
      .force(
        "radial",
        forceRadial((d) => RING_RADIUS[d.__hop] ?? 0, cx, cy).strength((d) => RING_STRENGTH[d.__hop] ?? 0)
      )
      .force(
        "collide",
        forceCollide((d) => radiusFor(d, entity.id) + 22)
      );

    function render() {
      linkSel
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      linkHitSel
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
    for (let i = 0; i < 200; i++) simulation.tick();
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

  const canExpand = neighbors.some((n) => (n.entity.neighbor_ids?.length ?? 0) > 0);

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
      {canExpand && (
        <button type="button" className="kg-expand-btn" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "− Ocultar 2º salto" : "+ Expandir conexões (2º salto)"}
        </button>
      )}
    </>
  );
}
