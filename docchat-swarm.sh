#!/bin/bash
# docchat-swarm.sh — 4 agent swarm + 1 monitor agent

BASE=/Users/divyanshu/desktop/FDE_Projects
PROJECT=$BASE/docchat

echo "🚀 Starting DocChat Agent Swarm..."

# Agent 1 — Performance Optimization
tmux new-session -d -s agent-perf \
  "cd $BASE/docchat-perf && claude 'You are a performance optimization expert. Analyze this FastAPI DocChat app with hybrid BM25+semantic retrieval, FlashRank reranking, Redis cache and SSE streaming. Identify bottlenecks, optimize slow endpoints, improve Redis cache hit rate, and reduce latency in the retrieval pipeline. Follow conventions in CLAUDE.md.'"

# Agent 2 — Docker & Deployment
tmux new-session -d -s agent-docker \
  "cd $BASE/docchat-docker && claude 'You are a DevOps expert. Set up production-ready Docker configuration for this DocChat FastAPI app. Create optimized multi-stage Dockerfile, docker-compose with all services (FastAPI, Redis, ARQ worker), health checks, nginx reverse proxy, .env.example, and production vs development profiles. Follow conventions in CLAUDE.md.'"

# Agent 3 — UI/UX Improvements
tmux new-session -d -s agent-ui \
  "cd $BASE/docchat-ui && claude 'You are a UI/UX expert. Improve the DocChat frontend. Add loading skeletons, better error states, keyboard shortcuts, mobile responsiveness, and improve the conversations panel UX. Follow conventions in CLAUDE.md.'"

# Agent 4 — Authentication
tmux new-session -d -s agent-auth \
  "cd $BASE/docchat-auth && claude 'You are a security expert. Add JWT-based authentication to this DocChat FastAPI app. Implement login, signup, logout, user model, protect all endpoints, bcrypt password hashing, and refresh token support. Follow conventions in CLAUDE.md.'"

# Agent 5 — Monitor + Feature Planner
tmux new-session -d -s agent-monitor \
  "cd $PROJECT && claude 'You are a senior engineer. Review the entire docchat codebase, check all existing features work correctly, identify bugs, and suggest the next 5 most impactful features. Write a detailed report to reports/docchat-audit.md. Follow conventions in CLAUDE.md.'"

echo ""
echo "✅ 5 agents running!"
echo ""
echo "Monitor with:        tmux ls"
echo "Watch agent-perf:    tmux attach -t agent-perf"
echo "Watch agent-docker:  tmux attach -t agent-docker"
echo "Watch agent-ui:      tmux attach -t agent-ui"
echo "Watch agent-auth:    tmux attach -t agent-auth"
echo "Watch agent-monitor: tmux attach -t agent-monitor"
echo ""
echo "Detach from any agent: Ctrl+B then D"
