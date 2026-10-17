import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "./components/RequireAuth";
import { Shell } from "./components/Shell";
import { AskPage } from "./routes/ask/AskPage";
import { Callback } from "./routes/Callback";
import { EvidencePage } from "./routes/evidence/EvidencePage";
import { NotFound } from "./routes/NotFound";
import { Placeholder } from "./routes/Placeholder";

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route
          index
          element={
            <RequireAuth>
              <AskPage />
            </RequireAuth>
          }
        />
        <Route path="callback" element={<Callback />} />
        <Route
          path="evidence/:chunkId"
          element={
            <RequireAuth>
              <EvidencePage />
            </RequireAuth>
          }
        />
        <Route
          path="library"
          element={
            <RequireAuth>
              <Placeholder title="Document library" />
            </RequireAuth>
          }
        />
        <Route
          path="evaluation"
          element={
            <RequireAuth>
              <Placeholder title="Evaluation" />
            </RequireAuth>
          }
        />
        <Route
          path="jobs"
          element={
            <RequireAuth admin>
              <Placeholder title="Ingestion jobs" />
            </RequireAuth>
          }
        />
        <Route
          path="feedback"
          element={
            <RequireAuth admin>
              <Placeholder title="Feedback review" />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
