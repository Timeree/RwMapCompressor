import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import javax.imageio.ImageIO;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerConfigurationException;
import javax.xml.transform.TransformerException;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.w3c.dom.Document;
import org.w3c.dom.NamedNodeMap;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;
import java.util.zip.GZIPInputStream;
import java.util.zip.InflaterInputStream;

/**
 @Author        Timeree
 @Version       1.1.2
 @Create Date   2024/02/26
 @Upgrade Date  2024/02/29
*/
public class RwMapCompressor {

  private static Base64.Encoder mB64Encoder = Base64.getEncoder();
  private static Base64.Decoder mB64Decoder = Base64.getDecoder();

  public static void main(String[] args) throws FileNotFoundException, SAXException, IOException, ParserConfigurationException, TransformerException {
    if (args.length == 0) {
      System.out.println("必需至少输入一个参数：值为绝对路径");
      return;
    }
    File inputFile = new File(args[0]);
    File outputFile = new File(inputFile.getParent() + "/output_rwmap.tmx");
    long startSize = inputFile.length();

    InputStream in = new FileInputStream(inputFile);
    OutputStream out = new FileOutputStream(outputFile);
    RwMapCompressor.output(in, out);
    in.close();
    out.close();

    long endSize = outputFile.length();
    System.out.println("《压缩结果》");
    System.out.println("输入路径：" + inputFile.getPath());
    System.out.println("输出路径：" + outputFile.getPath());
    System.out.println("压缩前大小：" + (startSize / 1024F) + " KB");
    System.out.println("压缩后大小：" + (endSize / 1024F) + " KB");
    System.out.println("压缩量：" + ((startSize - endSize) / 1024F) + " KB");
    System.out.println("压缩率：" + ((((float) startSize / endSize) - 1) * 100) + " %");
  }

  public static void output(InputStream input, OutputStream outStream) throws ParserConfigurationException, TransformerException, SAXException, IOException {
    output(input, outStream, false);
  }
  
  public static void output(InputStream input, OutputStream outStream, boolean isIgnoreUnitLayerImage) throws ParserConfigurationException, SAXException, IOException, TransformerConfigurationException, TransformerException {
    // isIgnoreUnitLayerImage 未实装
    DocumentBuilder docBuilder = DocumentBuilderFactory.newInstance().newDocumentBuilder();
    Document document = docBuilder.parse(input);
    HashMap<Node, Node> removeNodeList = new HashMap<>();
    HashMap<Integer, Object> tileIds = new HashMap<>();
    HashMap<Integer, Node> tiles = new HashMap<>();

    Node mapNode = document.getFirstChild();
    NamedNodeMap mapAttr = mapNode.getAttributes();
    int mapWidth = Integer.valueOf(mapAttr.getNamedItem("width").getNodeValue());
    int mapHeight = Integer.valueOf(mapAttr.getNamedItem("height").getNodeValue());

    NodeList nodeList = mapNode.getChildNodes();
    for (int i = 0; i < nodeList.getLength(); i++) {
      Node item = nodeList.item(i);
      if (item.getNodeType() == Node.ELEMENT_NODE) {
        if (item.getNodeName().equals("layer")) {
          Node data = findChildNode(item, "data");
          NamedNodeMap dataAttr = data.getAttributes();
          String encodeType = dataAttr.getNamedItem("encoding").getNodeValue();
          String compressionType = dataAttr.getNamedItem("compression").getNodeValue();
          String dataValue = data.getTextContent().replaceAll("[ \n]+", "");
          
          ByteBuffer buffer = null;
          if (encodeType.equals("base64")) {
            buffer = ByteBuffer.wrap(mB64Decoder.decode(dataValue));
          } else {
            throw new RuntimeException("不支持的 encoding 类型：" + encodeType);
          }
          if (compressionType.equals("gzip")) {
            buffer = decodeCompression("gzip", dataValue);
          } else if (compressionType.equals("zlib")) {
            buffer = decodeCompression("zlib", dataValue);
          } else {
            throw new RuntimeException("不支持的 layer.data.compression 类型：" + compressionType);
          }
          buffer.order(ByteOrder.LITTLE_ENDIAN);
          for (int index = 0; index < (mapWidth * mapHeight); index++) {
            int res = buffer.getInt();
            if (res != 0) {
              if (!tileIds.containsKey(res) && res < 0) {
                System.out.println("不支持小于 0 的地块 gid: " + res + " (使用了旋转角度?), 该地块会被忽略");
              }
              tileIds.put(res, true);
            }
          }
        }
      }
    }

    for (int i = 0; i < nodeList.getLength(); i++) {
      Node item = nodeList.item(i);
      if (item.getNodeType() == Node.ELEMENT_NODE) {
        if (item.getNodeName().equals("tileset")) {
          NamedNodeMap attr = item.getAttributes();
          NodeList tilesetList = item.getChildNodes();
          for (int i2 = 0; i2 < tilesetList.getLength(); i2++) {
            Node child = tilesetList.item(i2);
            if (child.getNodeType() == Node.ELEMENT_NODE) {
              String childName = child.getNodeName();
              int firstgId = Integer.valueOf(attr.getNamedItem("firstgid").getNodeValue());
              
              if (childName.equals("properties")) {
                Node property = findChildNode(child, "property");
                if (property.getAttributes().getNamedItem("name").getNodeValue().equals("embedded_png")) {
                  int tileWidth = Integer.valueOf(attr.getNamedItem("tilewidth").getNodeValue());
                  int tileHeight = Integer.valueOf(attr.getNamedItem("tileheight").getNodeValue());
                  ByteArrayInputStream imgInput = new ByteArrayInputStream(mB64Decoder.decode(property.getTextContent().replaceAll("[\n ]", "")));
                  ByteArrayOutputStream imgOutput = new ByteArrayOutputStream();
                  BufferedImage img = ImageIO.read(imgInput);
                  int imgWidth = img.getWidth();
                  int imgHeight = img.getHeight();
                  int tileColumnNum = (int) Math.floor(imgWidth / (float) tileWidth);
                  for (int x = 0; x < imgWidth; x++) {
                    for (int y = 0; y < imgHeight; y++) {
                      int tileX = (int) Math.floor(x / (float) tileWidth);
                      int tileY = (int) Math.floor(y / (float) tileHeight);
                      if (! tileIds.containsKey(firstgId + tileX + (tileY * tileColumnNum))) {
                        img.setRGB(x, y, 0x00000000);
                      }
                    }
                  }

                  ImageIO.write(img, "png", imgOutput);
                  property.setTextContent(mB64Encoder.encodeToString(imgOutput.toByteArray()));
                  imgInput.close();
                  imgOutput.close();
                }
              } else if (childName.equals("tile")) {
                NamedNodeMap childAttr = child.getAttributes();
                int id = Integer.valueOf(childAttr.getNamedItem("id").getNodeValue());
                if (! tileIds.containsKey(firstgId + id)) {
                  removeNodeList.put(child, item);
                } 
              } else {
                removeNodeList.put(child, item);
              }
            }
          }
        }
      }
    }

    // 最后统一删除无关节点，防止遍历出现问题
    for (Map.Entry<Node, Node> pair : removeNodeList.entrySet()) {
      pair.getValue().removeChild(pair.getKey());
    }

    Transformer transformer = TransformerFactory.newInstance().newTransformer();
    DOMSource source = new DOMSource(document);
    StreamResult result = new StreamResult(outStream);
    transformer.transform(source, result);
  }

  private static Node findChildNode(Node from, String name) {
    NodeList nodeList = from.getChildNodes();
    for (int i = 0; i < nodeList.getLength(); i++) {
      Node item = nodeList.item(i);
      if (item.getNodeType() == Node.ELEMENT_NODE && item.getNodeName().equals(name)) {
        return item;
      }
    }
    return null;
  }
  
  private static ByteBuffer decodeCompression(String type, String dataValue) throws IOException {
    InputStream inputStream;
    ByteArrayInputStream byteInput = new ByteArrayInputStream(mB64Decoder.decode(dataValue));
    ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
    if (type.equals("zlib")) {
      inputStream = new InflaterInputStream(byteInput);
    } else {
      inputStream = new GZIPInputStream(byteInput);
    }
    byte[] outBuffer = new byte[1024];
    int len;
    while ((len = inputStream.read(outBuffer)) != -1) {
      outputStream.write(outBuffer, 0, len);
    }
    ByteBuffer result = ByteBuffer.wrap(outputStream.toByteArray());
    byteInput.close();
    inputStream.close();
    outputStream.close();
    return result;
  }

}
