import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "./components/RequireAuth";
import { Shell } from "./components/Shell";
import { AskPage } from "./routes/ask/AskPage";
import { Callback } from "./routes/Callback";
import { EvidencePage } from "./routes/evidence/EvidencePage";
import { NotFound } from "./routes/NotFound";
import { EvaluationPage } from "./routes/evaluation/EvaluationPage";
import { FeedbackPage } from "./routes/feedback/FeedbackPage";
import { JobsPage } from "./routes/jobs/JobsPage";
import { DocumentPage } from "./routes/library/DocumentPage";
import { LibraryPage } from "./routes/library/LibraryPage";

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
              <LibraryPage />
            </RequireAuth>
          }
        />
        <Route
          path="library/:documentId"
          element={
            <RequireAuth>
              <DocumentPage />
            </RequireAuth>
          }
        />
        <Route
          path="evaluation"
          element={
            <RequireAuth>
              <EvaluationPage />
            </RequireAuth>
          }
        />
        <Route
          path="jobs"
          element={
            <RequireAuth admin>
              <JobsPage />
            </RequireAuth>
          }
        />
        <Route
          path="feedback"
          element={
            <RequireAuth admin>
              <FeedbackPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
