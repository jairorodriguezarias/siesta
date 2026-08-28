#!/bin/bash
# kb-manager.sh — Query and append to the KB graph
# Usage:
#   kb-manager.sh query <graph.json> [--type <type>] [--summary-only]
#   kb-manager.sh append-node <graph.json> <type> <summary> [detail]
#   kb-manager.sh append-edge <graph.json> <from_id> <to_id> <edge_type>
#   kb-manager.sh get-node <graph.json> <node_id>
#   kb-manager.sh list-all <graph.json>

set -e

GRAPH_FILE="${2:-./kb/graph.json}"

usage() {
  echo "Usage: kb-manager.sh <command> <graph.json> [args]" >&2
  echo "  query <graph> [--type <type>] [--summary-only]" >&2
  echo "  append-node <graph> <type> <summary> [detail]" >&2
  echo "  append-edge <graph> <from_id> <to_id> <edge_type>" >&2
  echo "  get-node <graph> <node_id>" >&2
  echo "  list-all <graph>" >&2
  exit 1
}

CMD="${1:-}"
[ -z "$CMD" ] && usage

case "$CMD" in
  query)
    GRAPH_FILE="$2"
    shift 2
    NODE_TYPE=""
    SUMMARY_ONLY=false
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --type) NODE_TYPE="$2"; shift 2 ;;
        --summary-only) SUMMARY_ONLY=true; shift ;;
        *) shift ;;
      esac
    done

    if [ "$SUMMARY_ONLY" = true ]; then
      if [ -n "$NODE_TYPE" ]; then
        jq -c --arg t "$NODE_TYPE" '[.nodes[] | select(.type == $t) | {id, type, summary}]' "$GRAPH_FILE" 2>/dev/null
      else
        jq -c '[.nodes[] | {id, type, summary}]' "$GRAPH_FILE" 2>/dev/null
      fi
    else
      if [ -n "$NODE_TYPE" ]; then
        jq -c --arg t "$NODE_TYPE" '[.nodes[] | select(.type == $t)]' "$GRAPH_FILE" 2>/dev/null
      else
        jq -c '.nodes' "$GRAPH_FILE" 2>/dev/null
      fi
    fi
    ;;

  append-node)
    GRAPH_FILE="$2"
    NODE_TYPE="$3"
    SUMMARY="$4"
    DETAIL="${5:-}"
    
    # Ensure parent directory exists (fixes 'No such file or directory')
    mkdir -p "$(dirname "$GRAPH_FILE")" 2>/dev/null
    if [ ! -f "$GRAPH_FILE" ]; then
      echo '{"nodes": [], "edges": []}' > "$GRAPH_FILE"
    fi
    
    # Generate unique ID
    NODE_ID="n$(date +%s)_$RANDOM"
    
    # Read schema to validate type
    SCHEMA_FILE="$(dirname "$GRAPH_FILE")/schema.json"
    if [ -f "$SCHEMA_FILE" ]; then
      VALID=$(jq -r --arg t "$NODE_TYPE" '.node_types | has($t)' "$SCHEMA_FILE" 2>/dev/null)
      if [ "$VALID" != "true" ]; then
        echo "Error: Invalid node type '$NODE_TYPE'" >&2
        exit 1
      fi
    fi

    # Append node
    jq --arg id "$NODE_ID" \
       --arg type "$NODE_TYPE" \
       --arg summary "$SUMMARY" \
       --arg detail "$DETAIL" \
       '.nodes += [{
         "id": $id,
         "type": $type,
         "summary": $summary,
         "detail": $detail,
         "created_at": (now | todate)
       }]' "$GRAPH_FILE" > "${GRAPH_FILE}.tmp" && mv "${GRAPH_FILE}.tmp" "$GRAPH_FILE"

    echo "$NODE_ID"
    ;;

  append-edge)
    GRAPH_FILE="$2"
    FROM_ID="$3"
    TO_ID="$4"
    EDGE_TYPE="$5"

    # Ensure parent directory and file exist
    mkdir -p "$(dirname "$GRAPH_FILE")" 2>/dev/null
    if [ ! -f "$GRAPH_FILE" ]; then
      echo '{"nodes": [], "edges": []}' > "$GRAPH_FILE"
    fi

    jq --arg from "$FROM_ID" \
       --arg to "$TO_ID" \
       --arg type "$EDGE_TYPE" \
       '.edges += [{
         "from": $from,
         "to": $to,
         "type": $type,
         "created_at": (now | todate)
       }]' "$GRAPH_FILE" > "${GRAPH_FILE}.tmp" && mv "${GRAPH_FILE}.tmp" "$GRAPH_FILE"

    echo "Edge created: $FROM_ID -> $TO_ID ($EDGE_TYPE)"
    ;;

  get-node)
    GRAPH_FILE="$2"
    NODE_ID="$3"
    jq --arg id "$NODE_ID" '.nodes[] | select(.id == $id)' "$GRAPH_FILE" 2>/dev/null
    ;;

  list-all)
    GRAPH_FILE="$2"
    jq -c '[.nodes[] | {id, type, summary}]' "$GRAPH_FILE" 2>/dev/null
    ;;

  init-project)
    GRAPH_FILE="$2"
    echo '{"nodes": [], "edges": []}' > "$GRAPH_FILE"
    echo "KB initialized at $GRAPH_FILE"
    ;;

  *)
    usage
    ;;
esac