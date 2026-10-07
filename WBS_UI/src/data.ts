import type { LucideIcon } from 'lucide-react'
import {
  ChartNoAxesCombined,
  CircleCheckBig,
  Clock3,
  FolderKanban,
  LayoutDashboard,
  ListTodo,
  Settings,
  Users,
} from 'lucide-react'

export type NavigationItem = {
  label: string
  icon: LucideIcon
}

export const navigation: NavigationItem[] = [
  { label: 'Overview', icon: LayoutDashboard },
  { label: 'Workstreams', icon: FolderKanban },
  { label: 'Tasks', icon: ListTodo },
  { label: 'Team', icon: Users },
  { label: 'Reports', icon: ChartNoAxesCombined },
]

export const secondaryNavigation: NavigationItem[] = [
  { label: 'Settings', icon: Settings },
]

export const metrics = [
  {
    label: 'Overall progress',
    value: '68%',
    detail: '8% ahead of plan',
    tone: 'green',
  },
  {
    label: 'Open tasks',
    value: '42',
    detail: '12 due this week',
    tone: 'orange',
  },
  {
    label: 'Team capacity',
    value: '82%',
    detail: '4 members available',
    tone: 'blue',
  },
  {
    label: 'Upcoming milestones',
    value: '6',
    detail: 'Next due 14 Oct',
    tone: 'red',
  },
]

export const workstreams = [
  {
    name: 'Discovery & planning',
    owner: 'Aarav Mehta',
    initials: 'AM',
    progress: 92,
    status: 'On track',
    tasks: '22 / 24 tasks',
  },
  {
    name: 'Experience design',
    owner: 'Maya Chen',
    initials: 'MC',
    progress: 74,
    status: 'On track',
    tasks: '17 / 23 tasks',
  },
  {
    name: 'Platform engineering',
    owner: 'Noah Williams',
    initials: 'NW',
    progress: 58,
    status: 'At risk',
    tasks: '29 / 50 tasks',
  },
  {
    name: 'Change enablement',
    owner: 'Priya Shah',
    initials: 'PS',
    progress: 43,
    status: 'On track',
    tasks: '10 / 23 tasks',
  },
]

export const tasks = [
  {
    title: 'Confirm migration acceptance criteria',
    meta: 'Platform engineering',
    date: 'Today',
    urgent: true,
  },
  {
    title: 'Review service blueprint',
    meta: 'Experience design',
    date: 'Tomorrow',
    urgent: false,
  },
  {
    title: 'Share readiness assessment',
    meta: 'Change enablement',
    date: '11 Oct',
    urgent: false,
  },
  {
    title: 'Approve sprint 4 scope',
    meta: 'Discovery & planning',
    date: '14 Oct',
    urgent: false,
  },
]

export const activity = [
  {
    icon: CircleCheckBig,
    title: 'Milestone completed',
    detail: 'Research synthesis was approved',
    time: '18 min ago',
  },
  {
    icon: Users,
    title: 'New team member',
    detail: 'Leena joined Platform engineering',
    time: '2 hr ago',
  },
  {
    icon: Clock3,
    title: 'Timeline updated',
    detail: 'UAT moved forward by two days',
    time: 'Yesterday',
  },
]

