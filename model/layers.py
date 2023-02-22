

import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers





def kernel_init(scale):
    scale = max(scale, 1e-10)
    return keras.initializers.VarianceScaling(
        scale, mode="fan_avg", distribution="truncated_normal"
    )



def normalize(inputs):
    in_channels = inputs.shape[-1]
    if in_channels <= 16:
        num_groups = in_channels // 4
    else:
        num_groups = 16
    x = layers.GroupNormalization(groups=num_groups,epsilon=1e-5,)(inputs)
    return x

def ResidualBlock(width,  activation_fn=keras.activations.swish):
    def apply(inputs):
        x= inputs
        input_width = x.shape[-1]

        if input_width == width:
            residual = x
        else:
            residual = layers.Conv2D(
                width, kernel_size=1, kernel_initializer=kernel_init(1.0)
            )(x)


        x = normalize(x)
        x = activation_fn(x)
        x = layers.Conv2D(
            width, kernel_size=3, padding="same", kernel_initializer=kernel_init(1.0)
        )(x)

        x=normalize(x)
        x = activation_fn(x)

        x = layers.Conv2D(
            width, kernel_size=3, padding="same", kernel_initializer=kernel_init(0.0)
        )(x)
        x = layers.Add()([x, residual])
        return x

    return apply



def DownSample(width,):
    def apply(x):
        x=tf.keras.layers.MaxPooling2D(pool_size=(2, 2))(x)
        return x

    return apply



def UpSample(width,activation_fn, interpolation="nearest",):
    def apply(x):
        x = layers.Conv2DTranspose(
            width, kernel_size=5, padding="same", strides=(2,2),kernel_initializer=kernel_init(1.0)
        )(x)
        x=normalize(x)
        x=activation_fn(x)
        return x

    return apply
def mlp(x, hidden_units, dropout_rate):
    for units in hidden_units:
        x = layers.Dense(units, activation=tf.nn.gelu)(x)
        x = layers.Dropout(dropout_rate)(x)
    return x

class Patches(layers.Layer):
    def __init__(self, patch_size):
        super().__init__()
        self.patch_size = patch_size

    def call(self, images):
        batch_size = tf.shape(images)[0]
        patches = tf.image.extract_patches(
            images=images,
            sizes=[1, self.patch_size, self.patch_size, 1],
            strides=[1, self.patch_size, self.patch_size, 1],
            rates=[1, 1, 1, 1],
            padding="VALID",
        )
        patch_dims = patches.shape[-1]
        patches = tf.reshape(patches, [batch_size, -1, patch_dims])
        return patches

class PatchEncoder(layers.Layer):
    def __init__(self, num_patches, projection_dim):
        super().__init__()
        self.num_patches = num_patches
        self.projection = layers.Dense(units=projection_dim)
        self.position_embedding = layers.Embedding(
            input_dim=num_patches, output_dim=projection_dim
        )

    def call(self, patch):
        positions = tf.range(start=0, limit=self.num_patches, delta=1)
        encoded = self.projection(patch) + self.position_embedding(positions)
        return encoded
        
class ReScaler(keras.layers.Layer):
  def __init__(self, orig_shape):
    super().__init__()
    self.orig_shape=orig_shape
    
  def build(self,input_shape):
    size_n=int(input_shape[1])//int(self.orig_shape[1])
   # self.max_pooling=tf.keras.layers.MaxPooling2D(pool_size=(size_n,size_n))
   # self.windowspatching=WindowPatches(int(self.orig_shape[1]))
    self.proj_out =  layers.Conv2D(int(input_shape[-1]),kernel_size=1,padding="same", kernel_initializer=kernel_init(1.0))

  def call(self, inputs):
      x = tf.image.resize(inputs, (self.orig_shape[1],self.orig_shape[2]), method="bilinear")
      return self.proj_out(x)


def gelu(x):
    tanh_res = keras.activations.tanh(x * 0.7978845608 * (1 + 0.044715 * (x**2)))
    return 0.5 * x * (1 + tanh_res)


def quick_gelu(x):
    return x * tf.sigmoid(x * 1.702)

class GEGLU(keras.layers.Layer):
    def __init__(self, dim_out):
        super().__init__()
        self.proj = layers.Conv2D(dim_out*2,kernel_size=1,padding="same", kernel_initializer=kernel_init(1.0))
        self.dim_out = dim_out

    def call(self, x):
        xp = self.proj(x)
        x, gate = xp[..., : self.dim_out], xp[..., self.dim_out :]
        return x * quick_gelu(gate)


class BasicTransformerBlock(keras.layers.Layer):
    def __init__(self, dim,):
        super().__init__()
        self.attn1 = AttentionBlock(dim)
        self.attn2 = CrossAttentionBlock(dim)
        self.geglu = GEGLU(dim * 4)
        self.dense  =layers.Conv2D(dim,kernel_size=1,padding="same", kernel_initializer=kernel_init(1.0))

    def call(self, inputs):
        x, context = inputs
        x = self.attn1(x) + x
        x = self.attn2([x, context]) + x
        return self.dense(self.geglu(x)) + x


class SpatialTransformer(keras.layers.Layer):
    def __init__(self, channels):
        super().__init__()
        self.norm = layers.GroupNormalization(groups=16,epsilon=1e-5)
        self.proj_in =  layers.Conv2D(channels,kernel_size=1,padding="same", kernel_initializer=kernel_init(1.0))
        self.transformer_blocks = [BasicTransformerBlock(channels)]
        self.proj_out = layers.Conv2D(channels,kernel_size=1,padding="same", kernel_initializer=kernel_init(1.0))

    def build(self,input_shape):
        shape=input_shape[0]
        self.scaler=ReScaler(orig_shape=shape)


    def call(self, inputs):
        x, context = inputs
        context = x if context is None else context
        if context is not None:
          context=self.scaler(context)
        x_in = x
        x = self.norm(x)
        x = self.proj_in(x)
        for block in self.transformer_blocks:
            x = block([x, context])
        return self.proj_out(x) + x_in

class CrossAttentionBlock(layers.Layer):
    """Applies cross-attention.

    Args:
        units: Number of units in the dense layers
        groups: Number of groups to be used for GroupNormalization layer
    """

    def __init__(self, units, groups=8, **kwargs):
        self.units = units
        self.groups = groups
        super().__init__(**kwargs)
    
        self.query = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.key = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.value = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.proj =layers.Dense(units,kernel_initializer=kernel_init(0))

    def build(self,input_shape):
        in_channels=input_shape[0][-1]
        if in_channels <= 16:
            groups = in_channels // 4
        else:
            groups = 16
        self.norm = layers.GroupNormalization(groups=groups)
        
    def call(self, inputs):
        inputs, context = inputs
        context = inputs if context is None else context

        batch_size = tf.shape(inputs)[0]
        height = tf.shape(inputs)[1]
        width = tf.shape(inputs)[2]
        scale = tf.cast(self.units, tf.float32) ** (-0.5)

        inputs = self.norm(inputs)
        q = self.query(inputs)
        k = self.key(context)
        v = self.value(context)

        attn_score = tf.einsum("bhwc, bHWc->bhwHW", q, k) * scale
        attn_score = tf.reshape(attn_score, [batch_size, height, width, height * width])

        attn_score = tf.nn.softmax(attn_score, -1)
        attn_score = tf.reshape(attn_score, [batch_size, height, width, height, width])

        proj = tf.einsum("bhwHW,bHWc->bhwc", attn_score, v)
        proj = self.proj(proj)
        return inputs + proj

def vit(inputs,patch_size,num_patches,transformer_layers,projection_dim,num_heads,transformer_units,mlp_head_units):
    # Augment data.
    # Create patches.
    patches = Patches(patch_size)(inputs)
    # Encode patches.
    encoded_patches = PatchEncoder(num_patches, projection_dim)(patches)

    # Create multiple layers of the Transformer block.
    for _ in range(transformer_layers):
        # Layer normalization 1.
        x1 = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
        # Create a multi-head attention layer.
        attention_output = layers.MultiHeadAttention(
            num_heads=num_heads, key_dim=projection_dim, dropout=0.1
        )(x1, x1)
        # Skip connection 1.
        x2 = layers.Add()([attention_output, encoded_patches])
        # Layer normalization 2.
        x3 = layers.LayerNormalization(epsilon=1e-6)(x2)
        # MLP.
        x3 = mlp(x3, hidden_units=transformer_units, dropout_rate=0.1)
        # Skip connection 2.
        encoded_patches = layers.Add()([x3, x2])
         
    representation = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
    features = mlp(representation, hidden_units=[x/2 for x in mlp_head_units], dropout_rate=0.5)


    return features

class AttentionBlock(layers.Layer):
    """Applies self-attention.
    Args:
        units: Number of units in the dense layers
        groups: Number of groups to be used for GroupNormalization layer
    """

    def __init__(self, units, groups=8, **kwargs):
        self.units = units
        self.groups = groups
        super().__init__(**kwargs)

        self.query = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.key = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.value = layers.Dense(units, kernel_initializer=kernel_init(1.0))
        self.proj =layers.Dense(units,kernel_initializer=kernel_init(0))

    def build(self,input_shape):
        in_channels=input_shape[-1]
        if in_channels <= 16:
            groups = in_channels // 4
        else:
            groups = 16
        self.norm = layers.GroupNormalization(groups=groups)

        
    def call(self, inputs):
        batch_size = tf.shape(inputs)[0]
        height = tf.shape(inputs)[1]
        width = tf.shape(inputs)[2]
        scale = tf.cast(self.units, tf.float32) ** (-0.5)

        q = self.query(inputs)
        k = self.key(inputs)
        v = self.value(inputs)

        attn_score = tf.einsum("bhwc, bHWc->bhwHW", q, k) * scale
        attn_score = tf.reshape(attn_score, [batch_size, height, width, height * width])

        attn_score = tf.nn.softmax(attn_score, -1)
        attn_score = tf.reshape(attn_score, [batch_size, height, width, height, width])

        proj = tf.einsum("bhwHW,bHWc->bhwc", attn_score, v)
        proj = self.proj(proj)
        return inputs + proj