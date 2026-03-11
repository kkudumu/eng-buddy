import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import App from './App'
import { TasksView } from './features/tasks/TasksView'
import { JiraSprintView } from './features/jira/JiraSprintView'
import { CalendarView } from './features/calendar/CalendarView'
import { DailyLogView } from './features/daily/DailyLogView'
import { LearningsView } from './features/learnings/LearningsView'
import { KnowledgeView } from './features/knowledge/KnowledgeView'
import { SuggestionsView } from './features/suggestions/SuggestionsView'
import { PlaybooksView } from './features/playbooks/PlaybooksView'

export const router = createBrowserRouter(
  [
    {
      path: '/app',
      element: <AppLayout />,
      children: [
        { index: true, element: <Navigate to="inbox" replace /> },
        { path: 'inbox', element: <App /> },
        { path: 'inbox/:source', element: <App /> },
        { path: 'tasks', element: <TasksView /> },
        { path: 'jira', element: <JiraSprintView /> },
        { path: 'calendar', element: <CalendarView /> },
        { path: 'daily', element: <DailyLogView /> },
        { path: 'learnings', element: <LearningsView /> },
        { path: 'knowledge', element: <KnowledgeView /> },
        { path: 'suggestions', element: <SuggestionsView /> },
        { path: 'playbooks', element: <PlaybooksView /> },
      ],
    },
  ],
  { basename: '/' },
)
