import '@testing-library/jest-dom/vitest'
import React from 'react'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

Object.assign(globalThis, { React })
afterEach(cleanup)
