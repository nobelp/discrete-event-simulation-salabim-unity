using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class SimulateHandler : MonoBehaviour
{
    [SerializeField] private Transform mainPanel;
    [SerializeField] private TMP_Text statusText;
    [SerializeField] private TMP_InputField simSpeedInputField;
    [SerializeField] private TMP_InputField simDurationInputField;

    private void Start()
    {
        var panel = gameObject.AddComponent<KxSimulationPanel>();
        panel.Init(mainPanel, statusText, simDurationInputField);
        // The old animation speed has no meaning in a headless simulated-time run.
        if (simSpeedInputField != null) simSpeedInputField.interactable = false;
        GetComponent<Button>().onClick.AddListener(panel.Open);
    }
}
