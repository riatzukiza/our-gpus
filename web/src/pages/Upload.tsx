import { useState } from "react";
import {
  Upload as UploadIcon,
  FileJson,
  AlertCircle,
  CheckCircle,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import FieldMapper from "../components/FieldMapper";
import ProgressBar from "../components/ProgressBar";

export default function Upload() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [schema, setSchema] = useState<any>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [scanId, setScanId] = useState<number | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [detectedFormat, setDetectedFormat] = useState<string | null>(null);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setFile(file);
    setSchema(null);
    setParseError(null);
    setError(null);
    setDetectedFormat(null);

    // Sample file to infer schema
    const reader = new FileReader();
    reader.onload = async (e) => {
      const text = e.target?.result as string;
      
      // For JSONL detection and parsing, we want complete lines only
      // Find the last complete newline to avoid partial JSON strings
      let completeText = text;
      const lastNewline = text.lastIndexOf('\n');
      if (lastNewline > 0 && lastNewline < text.length - 1) {
        // Only use text up to the last complete line
        completeText = text.substring(0, lastNewline);
      }
      
      const lines = completeText.split("\n").slice(0, 20).filter(l => l.trim());

      try {
        // Check if this is a text file with ip:port format
        if (file.name.endsWith(".txt")) {
          const textRecords = lines
            .filter((l) => l.trim() && l.includes(":"))
            .map((l) => {
              const [ip, port] = l.trim().split(":");
              return { ip: ip?.trim(), port: parseInt(port?.trim()) };
            })
            .filter((r) => r.ip && !isNaN(r.port));

          if (textRecords.length > 0) {
            setSchema({
              fields: { ip: "string", port: "number" },
              sample_records: textRecords.slice(0, 3),
            });
            setMapping({ ip: "ip", port: "port" });
            return;
          }
        }

        // JSON/JSONL parsing
        let sampleRecords = [];
        
        // First, try to detect if this looks like JSONL by checking if first few lines are valid JSON objects
        const firstFewLines = lines.slice(0, 3).filter(l => l.trim());
        let looksLikeJsonl = false;
        
        if (firstFewLines.length > 0) {
          const validJsonLines = firstFewLines.filter(line => {
            try {
              const parsed = JSON.parse(line.trim());
              return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed);
            } catch {
              return false;
            }
          });
          looksLikeJsonl = validJsonLines.length >= Math.min(2, firstFewLines.length);
        }
        
        if (looksLikeJsonl || file.name.endsWith(".jsonl")) {
          // Parse as JSONL (line by line)
          setDetectedFormat("JSONL (JSON Lines)");
          sampleRecords = lines
            .filter((l) => l.trim())
            .map((l, index) => {
              try {
                return JSON.parse(l.trim());
              } catch (lineError) {
                console.warn(`Failed to parse line ${index + 1}: ${l.trim()}`);
                return null;
              }
            })
            .filter(record => record !== null)
            .slice(0, 10);
        } else {
          // Try to parse as complete JSON (array or object)
          try {
            const fullContent = JSON.parse(completeText.trim());
            if (Array.isArray(fullContent)) {
              setDetectedFormat("JSON Array");
              sampleRecords = fullContent.slice(0, 10);
            } else if (typeof fullContent === 'object' && fullContent !== null) {
              setDetectedFormat("JSON Object");
              sampleRecords = [fullContent];
            }
          } catch (jsonError) {
            // If complete JSON parsing fails, try JSONL as fallback
            try {
              sampleRecords = lines
                .filter((l) => l.trim())
                .map((l) => {
                  try {
                    return JSON.parse(l.trim());
                  } catch {
                    return null;
                  }
                })
                .filter(record => record !== null)
                .slice(0, 10);
                
              if (sampleRecords.length === 0) {
                setParseError(`Unable to parse file as JSON or JSONL. Error: ${jsonError instanceof Error ? jsonError.message : 'Unknown parsing error'}`);
                return;
              } else {
                setDetectedFormat("JSONL (auto-detected)");
              }
            } catch {
              setParseError(`Invalid JSON format: ${jsonError instanceof Error ? jsonError.message : 'Unable to parse JSON'}`);
              return;
            }
          }
        }

        if (sampleRecords.length === 0) {
          setParseError("No valid JSON records found. Please check your file format.");
          return;
        }

        const fields: Record<string, string> = {};
        sampleRecords.forEach((record) => {
          if (record && typeof record === 'object') {
            Object.keys(record).forEach((key) => {
              if (!fields[key]) {
                const value = record[key];
                if (value === null || value === undefined) {
                  fields[key] = 'null';
                } else if (Array.isArray(value)) {
                  fields[key] = 'array';
                } else {
                  fields[key] = typeof value;
                }
              }
            });
          }
        });

        setSchema({
          fields,
          sample_records: sampleRecords.slice(0, 3),
        });

        // Auto-detect common mappings
        const autoMapping: Record<string, string> = {};
        
        // IP address mapping
        if ("ip" in fields) autoMapping.ip = "ip";
        else if ("host" in fields) autoMapping.ip = "host";
        else if ("address" in fields) autoMapping.ip = "address";
        else if ("ip_address" in fields) autoMapping.ip = "ip_address";
        
        // Port mapping
        if ("port" in fields) autoMapping.port = "port";
        else if ("port_number" in fields) autoMapping.port = "port_number";
        
        // Geography mappings
        if ("country" in fields) autoMapping.geo_country = "country";
        else if ("geo_country" in fields) autoMapping.geo_country = "geo_country";
        else if ("country_code" in fields) autoMapping.geo_country = "country_code";
        
        if ("city" in fields) autoMapping.geo_city = "city";
        else if ("geo_city" in fields) autoMapping.geo_city = "geo_city";
        
        // Tags mapping
        if ("tags" in fields) autoMapping.tags = "tags";
        else if ("tag" in fields) autoMapping.tags = "tag";
        else if ("labels" in fields) autoMapping.tags = "labels";

        setMapping(autoMapping);
      } catch (err) {
        console.error("Failed to parse sample:", err);
        setParseError(`Failed to parse file: ${err instanceof Error ? err.message : 'Unknown error'}`);
      }
    };

    // Read first 200KB to get enough sample data while avoiding memory issues
    const sampleSize = Math.min(file.size, 200000);
    reader.readAsText(file.slice(0, sampleSize));
  };

  const resetUpload = () => {
    setFile(null);
    setSchema(null);
    setMapping({});
    setError(null);
    setParseError(null);
    setDetectedFormat(null);
    setCompleted(false);
    setProgress(0);
    setScanId(null);
  };

  const handleUpload = async () => {
    if (!file || !mapping) return;

    setUploading(true);
    setError(null);
    setCompleted(false);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("field_map", JSON.stringify(mapping));
    formData.append("source", "upload");

    try {
      const response = await axios.post("/api/ingest", formData);
      setScanId(response.data.scan_id);

      // If status is already completed (for txt files), redirect immediately
      if (response.data.status === "completed") {
        setCompleted(true);
        setUploading(false);
        setTimeout(() => {
          navigate("/");
        }, 1000); // Give user time to see success message
        return;
      }

      // Poll for progress for other file types
      const pollInterval = setInterval(async () => {
        try {
          const scanResponse = await axios.get(
            `/api/scans/${response.data.scan_id}`,
          );
          const scan = scanResponse.data;

          if (scan.total_rows > 0) {
            setProgress((scan.processed_rows / scan.total_rows) * 100);
          }

          if (scan.status === "completed") {
            clearInterval(pollInterval);
            setCompleted(true);
            setUploading(false);
            setTimeout(() => {
              navigate("/");
            }, 2000);
          } else if (scan.status === "failed") {
            clearInterval(pollInterval);
            setUploading(false);
            setError(scan.error_message || "Processing failed");
          }
        } catch (pollErr) {
          clearInterval(pollInterval);
          setUploading(false);
          setError("Failed to check processing status");
        }
      }, 1000);
    } catch (err: any) {
      console.error("Upload failed:", err);
      setUploading(false);

      // Extract detailed error message
      let errorMessage = "Upload failed";
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
          errorMessage = err.response.data.detail
            .map((e: any) => `${e.loc?.join(".")}: ${e.msg}`)
            .join(", ");
        } else {
          errorMessage = err.response.data.detail;
        }
      } else if (err.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err.message) {
        errorMessage = err.message;
      }

      setError(errorMessage);
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-6">
        Upload Data
      </h2>

      {!file && (
        <div className="border-2 border-dashed rounded-lg p-12 text-center transition-colors border-gray-300 dark:border-gray-600 hover:border-gray-400 dark:hover:border-gray-500 bg-white dark:bg-gray-800">
          <input
            type="file"
            accept=".json,.jsonl,.txt"
            onChange={handleFileSelect}
            className="hidden"
            id="file-upload"
          />
          <label htmlFor="file-upload" className="cursor-pointer">
            <UploadIcon className="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <p className="text-lg font-medium text-gray-900">
              Click to upload your file
            </p>
            <p className="text-sm text-gray-500 mt-2">or drag & drop</p>
            <p className="text-xs text-gray-400 mt-4">
              Supports JSON, JSONL, and TXT (ip:port) formats up to 4GB
            </p>
          </label>
        </div>
      )}

      {file && !uploading && !completed && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <div className="flex items-center mb-4">
            <FileJson className="h-8 w-8 text-blue-500 mr-3" />
            <div>
              <p className="font-medium text-gray-900 dark:text-white">{file.name}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {(file.size / (1024 * 1024)).toFixed(2)} MB
              </p>
            </div>
          </div>

          {(error || parseError) && (
            <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/50 border border-red-200 dark:border-red-800 rounded-lg">
              <div className="flex items-start">
                <AlertCircle className="h-5 w-5 text-red-500 mr-2 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-red-800 dark:text-red-200">
                    {error ? 'Upload Failed' : 'Parse Error'}
                  </p>
                  <p className="text-sm text-red-700 dark:text-red-300 mt-1">
                    {error || parseError}
                  </p>
                </div>
              </div>
            </div>
          )}

          {detectedFormat && (
            <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/50 border border-blue-200 dark:border-blue-800 rounded-lg">
              <p className="text-sm text-blue-800 dark:text-blue-200">
                <span className="font-medium">Detected format:</span> {detectedFormat}
              </p>
            </div>
          )}

          {schema && (
            <>
              <FieldMapper
                schema={schema}
                mapping={mapping}
                onMappingChange={setMapping}
              />

              <div className="mt-6 flex gap-4">
                <button
                  onClick={handleUpload}
                  className="flex-1 bg-blue-600 text-white py-2 px-4 rounded-lg hover:bg-blue-700 transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed"
                  disabled={!mapping.ip}
                >
                  Start Ingestion
                </button>
                <button
                  onClick={resetUpload}
                  className="px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                >
                  Choose Different File
                </button>
              </div>
            </>
          )}

          {!schema && !parseError && (
            <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/50 border border-blue-200 dark:border-blue-800 rounded-lg">
              <p className="text-sm text-blue-800 dark:text-blue-200">
                Parsing file... Please wait while we analyze your data structure.
              </p>
            </div>
          )}

          {parseError && !schema && (
            <div className="mt-4 flex gap-4">
              <button
                onClick={resetUpload}
                className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                Choose Different File
              </button>
            </div>
          )}
        </div>
      )}

      {uploading && !completed && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Processing...</h3>
          <ProgressBar progress={progress} />
          {scanId && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">Scan ID: {scanId}</p>
          )}
        </div>
      )}

      {completed && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
          <div className="flex items-center justify-center mb-4">
            <CheckCircle className="h-12 w-12 text-green-500 mr-4" />
            <div>
              <h3 className="text-lg font-medium text-green-800 dark:text-green-400">
                Upload Completed!
              </h3>
              <p className="text-sm text-green-600 dark:text-green-500">
                Redirecting to hosts page...
              </p>
            </div>
          </div>
          {scanId && (
            <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
              Scan ID: {scanId}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
