using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Diagnostics;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TMPro;
using UnityEngine;

public class KxSimulationPanel : MonoBehaviour
{
    private Transform panel;
    private TMP_Text status;
    private TMP_InputField durationInput;
    private bool visible, syntheticConfirmed;
    private Rect rect = new Rect(40, 40, 740, 630);
    private string root = "", python = "", duration = "", jobs = "", message = "", savedScenario = "";
    private Task<string> running;
    public void Init(Transform mainPanel, TMP_Text statusText, TMP_InputField durationField)
    {
        panel = mainPanel; status = statusText; durationInput = durationField;
        root = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
        python = Path.Combine(root, ".venv", "Scripts", "python.exe");
    }
    public void Open() { duration = durationInput.text; visible = true; }
    private void Update()
    {
        if (running == null || !running.IsCompleted) return;
        try { message = running.GetAwaiter().GetResult(); }
        catch (Exception e) { message = "Fehler: " + e.GetBaseException().Message; }
        status.text = message; running = null;
    }
    private void OnGUI() { if (visible) rect = GUI.Window(GetInstanceID(), rect, Draw, "KX – geprüften Simulationskern starten"); }
    private void Draw(int id)
    {
        GUILayout.Label("Zonen per Rechtsklick konfigurieren. Verbindungen und Routen werden nicht aus Pixelpositionen abgeleitet.");
        GUILayout.Label("Repository-Ordner"); root = GUILayout.TextField(root);
        GUILayout.Label("Python der eingerichteten Umgebung"); python = GUILayout.TextField(python);
        GUILayout.Label("Messdauer [s]"); duration = GUILayout.TextField(duration);
        GUILayout.Label("Transporte: ID; Ankunft in s; Route als kommagetrennte Zonen-IDs (eine Zeile je Transport)");
        jobs = GUILayout.TextArea(jobs, GUILayout.Height(90));
        syntheticConfirmed = GUILayout.Toggle(syntheticConfirmed, "Dies ist ausdrücklich ein synthetischer Prüffall, kein Anlagenleistungsnachweis");
        GUI.enabled = running == null;
        if (GUILayout.Button("Aktuelle Zonen und Transporte simulieren")) TryRun(false);
        GUILayout.Label("Gespeicherte kx-unity-zones-Szenariodatei (optional)"); savedScenario = GUILayout.TextField(savedScenario);
        if (GUILayout.Button("Gespeicherten Prüffall simulieren")) TryRun(true);
        GUI.enabled = true;
        GUILayout.Label(message);
        if (GUILayout.Button("Schliessen")) visible = false;
        GUI.DragWindow();
    }
    private JObject Build()
    {
        double seconds;
        if (!Double.TryParse(duration.Replace(',', '.'), NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out seconds) || Double.IsNaN(seconds) || Double.IsInfinity(seconds) || seconds <= 0)
            throw new ArgumentException("Positive Messdauer erforderlich.");
        var segments = new JArray(); var ids = new HashSet<string>();
        foreach (Transform entry in panel)
        {
            if (!entry.CompareTag("Conveyor")) continue;
            var moving = entry.GetComponent<AbstractMoveable>();
            if (moving == null || !moving.isActive || moving.isMoveing) throw new ArgumentException("Alle Förderzonen zuerst fertig platzieren.");
            var zone = entry.GetComponent<KxZoneSettings>();
            if (zone == null) throw new ArgumentException("Förderzone per Rechtsklick konfigurieren: " + entry.name);
            if (!ids.Add(zone.Id)) throw new ArgumentException("Doppelte Zonen-ID: " + zone.Id);
            if (!zone.connectionsConfirmed) throw new ArgumentException(zone.Id + ": Verbindungen bestätigen.");
            segments.Add(new JObject { ["id"] = zone.Id, ["mode"] = "constant_speed_exclusive_zone",
                ["lengthM"] = zone.Number(zone.lengthM, "Weglänge", false), ["speedMps"] = zone.Number(zone.speedMps, "Geschwindigkeit", false),
                ["transferSeconds"] = zone.Number(zone.transferSeconds, "Übergabezeit", true),
                ["nextIds"] = new JArray(zone.nextIds.Split(',').Select(s => s.Trim()).Where(s => s.Length > 0)), ["connectionsConfirmed"] = true,
                ["screenPosition"] = new JObject { ["x"] = entry.position.x, ["y"] = entry.position.y } });
        }
        var transports = new JArray();
        foreach (var line in jobs.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = line.Split(';'); double arrival;
            if (parts.Length != 3 || !Double.TryParse(parts[1].Trim().Replace(',', '.'), NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out arrival))
                throw new ArgumentException("Transportformat: ID;Ankunft;Zone1,Zone2");
            transports.Add(new JObject { ["id"] = parts[0].Trim(), ["arrivalSeconds"] = arrival, ["route"] = new JArray(parts[2].Split(',').Select(s => s.Trim())) });
        }
        if (transports.Count == 0) throw new ArgumentException("Mindestens einen Transport eingeben.");
        return new JObject { ["format"] = "kx-unity-zones", ["version"] = 1, ["dataStatus"] = "synthetic", ["durationSeconds"] = seconds, ["seed"] = 42, ["segments"] = segments, ["jobs"] = transports };
    }
    private void TryRun(bool fromFile)
    {
        try
        {
            if (!syntheticConfirmed) throw new ArgumentException("Synthetischen Prüffall zuerst ausdrücklich bestätigen.");
            if (!File.Exists(python) || !File.Exists(Path.Combine(root, "kx", "unity_bridge.py"))) throw new ArgumentException("Python und Repository-Ordner prüfen (siehe KX-README).");
            var payload = fromFile ? JObject.Parse(File.ReadAllText(savedScenario)) : Build();
            string folder = Path.Combine(Application.persistentDataPath, "kx-runs", Guid.NewGuid().ToString("N")); Directory.CreateDirectory(folder);
            string input = Path.Combine(folder, "scenario.json"), output = Path.Combine(folder, "result.json");
            File.WriteAllText(input, payload.ToString(Formatting.Indented));
            string exe = python, work = root;
            message = "Simulation läuft …"; status.text = message;
            running = Task.Run(() => Execute(exe, work, input, output));
        }
        catch (Exception e) { message = "Eingabe prüfen: " + e.Message; status.text = message; }
    }
    private static string Quote(string value)
    {
        if (value.Contains("\"") || value.Contains("\n") || value.Contains("\r")) throw new ArgumentException("Ungültiger Dateipfad.");
        return "\"" + value + "\"";
    }
    private static string Execute(string exe, string root, string input, string output)
    {
        var info = new ProcessStartInfo { FileName = exe, WorkingDirectory = root,
            Arguments = "-m kx.unity_bridge " + Quote(input) + " --output " + Quote(output),
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        using (var process = new Process { StartInfo = info })
        {
            process.Start(); var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(60000)) { process.Kill(); throw new TimeoutException("Simulation nach 60 Sekunden abgebrochen."); }
            string error = stderr.GetAwaiter().GetResult(); stdout.GetAwaiter().GetResult();
            if (process.ExitCode != 0) throw new InvalidOperationException(error);
        }
        var result = JObject.Parse(File.ReadAllText(output));
        return "Synthetisch: abgeschlossen " + result["completed"] + ", offen " + result["unfinished"] + ", BE/h " + result["completedPerHour"] +
            " · " + result["deadlockDiagnostic"]["status"] + "\nSzenario: " + input + "\nErgebnis: " + output;
    }
}
