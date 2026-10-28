import { lazy } from 'react'

export const MockupLayout = lazy(() => import('./Mockup.tsx').then((module) => ({ default: module.MockupLayout })))
export const MockupCatalog = lazy(() => import('./Mockup.tsx').then((module) => ({ default: module.MockupCatalog })))
export const MockupScreen = lazy(() => import('./Mockup.tsx').then((module) => ({ default: module.MockupScreen })))
