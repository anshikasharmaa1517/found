import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// The whole suite runs in parallel; a cold first render can take over a second there.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => cleanup());
