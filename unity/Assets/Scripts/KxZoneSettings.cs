using System;
using System.Globalization;
using UnityEngine;

// Runtime form: no scene/prefab wiring is required.
public class KxZoneSettings : MonoBehaviour
{
    [SerializeField] private string stableId = "";
    public string lengthM = "";
    public string speedMps = "";
    public string transferSeconds = "";
    public string nextIds = "";
    public bool connectionsConfirmed;
    private bool visible;
    private Rect rect = new Rect(30, 40, 540, 410);
    public string Id { get { if (String.IsNullOrWhiteSpace(stableId)) ResetIdentity(); return stableId; } }
    public void ResetIdentity() { stableId = "zone-" + Guid.NewGuid().ToString("N").Substring(0, 10); }
    public void Open() { var unused = Id; visible = true; }
    private void OnGUI() { if (visible) rect = GUI.Window(GetInstanceID(), rect, Draw, "Förderzone – synthetisches Einplatzmodell"); }
    private string Field(string label, string value) { GUILayout.Label(label); return GUILayout.TextField(value ?? ""); }
    private void Draw(int id)
    {
        stableId = Field("Stabile Zonen-ID (für Verbindungen und Routen)", Id);
        lengthM = Field("Weglänge [m]", lengthM);
        speedMps = Field("Konstante Geschwindigkeit [m/s]", speedMps);
        transferSeconds = Field("Zusätzliche Übergabezeit [s], auch 0 ausdrücklich eingeben", transferSeconds);
        nextIds = Field("Erlaubte Folge-IDs, durch Komma getrennt; leer = Endpunkt", nextIds);
        connectionsConfirmed = GUILayout.Toggle(connectionsConfirmed, "Richtung und Endpunkt/Folge-IDs ausdrücklich geprüft");
        GUILayout.Label("Ein Transport belegt die ganze Zone bis zur Übergabe. Keine Beschleunigung, Behälterteilung oder Mehrfachbelegung.");
        if (GUILayout.Button("Schliessen")) visible = false;
        GUI.DragWindow();
    }
    public double Number(string text, string label, bool zero)
    {
        double value;
        if (!Double.TryParse((text ?? "").Trim().Replace(',', '.'), NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out value) || Double.IsNaN(value) || Double.IsInfinity(value) || (zero ? value < 0 : value <= 0))
            throw new ArgumentException(Id + ": " + label + " fehlt oder ist ungültig.");
        return value;
    }
}
