// Compile-only API shapes. This does not emulate or validate the Unity editor.
using System;
using System.Collections;
namespace UnityEngine {
 [AttributeUsage(AttributeTargets.Field)] public class SerializeField : Attribute {}
 public class MonoBehaviour { public GameObject gameObject = new GameObject(); public T GetComponent<T>() where T:class=>null; public int GetInstanceID()=>1; }
 public class GameObject { public T AddComponent<T>() where T:new()=>new T(); public T GetComponent<T>() where T:class=>null; }
 public class Transform : IEnumerable { public string name; public Vector3 position; public bool CompareTag(string s)=>true; public T GetComponent<T>() where T:class=>null; public IEnumerator GetEnumerator()=>new object[0].GetEnumerator(); }
 public struct Vector3 { public float x,y; }
 public struct Rect { public Rect(float x,float y,float w,float h){} }
 public static class GUI { public static bool enabled; public static Rect Window(int id,Rect r,Action<int> action,string title)=>r; public static void DragWindow(){} }
 public class GUILayoutOption {}
 public static class GUILayout { public static void Label(string s){} public static string TextField(string s)=>s; public static string TextArea(string s,params GUILayoutOption[] o)=>s; public static GUILayoutOption Height(float v)=>null; public static bool Toggle(bool b,string s)=>b; public static bool Button(string s)=>false; }
 public static class Application { public static string dataPath="",persistentDataPath=""; }
}
namespace TMPro { public class TMP_Text {public string text;} public class TMP_InputField {public string text; public bool interactable;} }
public class AbstractMoveable { public bool isActive,isMoveing; }

namespace UnityEngine.UI { public class Button { public ClickEvent onClick = new ClickEvent(); } public class ClickEvent {public void AddListener(Action action){} } }
