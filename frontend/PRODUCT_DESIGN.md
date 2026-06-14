# EduVault Frontend Architecture

## Information Architecture

- Dashboard: system health, repository activity, quick actions.
- Repository: folder tree, document explorer, AI-assisted import, document viewer.
- AI Assistant: conversations, grounded answers, source references.
- Knowledge Transfer: course handover workspaces, timelines, experience and FAQ.
- Version Control: document history, compare, rollback and audit log.
- Backup & Recovery: 3-2-1 overview, schedules, history and restore center.
- Permissions: users, roles, permission matrix and access requests.
- Reports: search, views, storage, activity and quality metrics.
- Settings: workspace, AI, integrations, security, notifications and taxonomy.

## Primary User Flows

1. Import: Repository → Upload → AI analysis → Review metadata/folder → Store.
2. Discover: Global search → Results → Document viewer → Related sources.
3. Ask: AI Assistant → Question → Grounded answer → Open cited document.
4. Transfer: Knowledge Transfer → Select course → Complete knowledge checklist → Confirm handover.
5. Recover: Backup Center → Select snapshot → Review → Restore.

## Component Architecture

- `AppShell`: responsive sidebar, top navigation, global search and dark mode.
- `PageHeader`, `Metric`, `Panel`, `Bars`, `EmptyState`: reusable interface primitives.
- `lib/data.ts`: centralized mock data, ready to replace with backend clients.
- `app/*`: route-level compositions using shared components and design tokens.
