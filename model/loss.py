import tensorflow.keras.backend as K
import tensorflow as tf 
import numpy as np


class JaccardLoss(tf.keras.losses.Loss):
    def __init__(self, smooth=1,**kwargs):
        super().__init__(**kwargs)
        self.smooth=smooth

    def call(self, y_true, y_pred):
      intersection = K.sum(K.abs(y_true * y_pred), axis=[1,2,3])
      union = K.sum(y_true,[1,2,3])+K.sum(y_pred,[1,2,3])-intersection
      iou = K.mean((intersection + self.smooth) / (union + self.smooth), axis=0)
      return (1-iou)



class DiceLoss(tf.keras.losses.Loss):
 
    def __init__(self, weight,smooth=1,**kwargs):
        super().__init__(**kwargs)
        self.smooth=smooth
        self.epsilon=K.epsilon()
        self.alpha=0.5
        self.beta=0.5
        self.weight = weight

    def call(self, y_true, y_pred):

        intersection = K.sum(K.abs(y_true * y_pred), axis=[1,2])
        union = K.sum(y_true, axis=[1,2,]) + K.sum(y_pred, axis=[1,2])
        dice= K.mean( (2. * intersection + self.smooth) / (union + self.smooth), axis=0)

        return (1-dice)
    
class ComboLoss(tf.keras.losses.Loss):
    """
    It is not working well
    """
    def __init__(self, smooth=1,**kwargs):
        super().__init__(**kwargs)
        self.smooth=smooth
        self.epsilon=K.epsilon()
        self.alpha=0.5
        self.beta=0.5
        self.bce = tf.keras.losses.BinaryCrossentropy(from_logits=True,reduction=tf.keras.losses.Reduction.NONE)

    def call(self, y_true, y_pred):

        intersection = K.sum(K.abs(y_true * y_pred), axis=[1,2,3])
        union = K.sum(y_true, axis=[1,2,3]) + K.sum(y_pred, axis=[1,2,3])
        dice= K.mean( (2. * intersection + self.smooth) / (union + self.smooth), axis=0)

        y_pred = K.clip(y_pred, self.epsilon, 1. - self.epsilon)
        cross_entropy = self.bce(K.flatten(y_true),K.flatten(y_pred))
        beta_weight = np.array([self.beta, 1-self.beta])
        cross_entropy = beta_weight * cross_entropy
        # sum over classes
        cross_entropy = K.mean(K.sum(cross_entropy, axis=[-1]))
        combo_loss = (self.alpha * cross_entropy) - ((1 - self.alpha) * dice)
        return combo_loss




class GeneralizedDice(tf.keras.losses.Loss):
    def __init__(self, smooth=1,**kwargs):
        super().__init__(**kwargs)
        self.epsilon=K.epsilon()


    def call(self, y_true, y_pred):

        # [b, h, w, classes]
        y_true_shape = tf.shape(y_true)

        # [b, h*w, classes]
        y_true = tf.reshape(y_true, [-1, y_true_shape[1]*y_true_shape[2], y_true_shape[3]])
        y_pred = tf.reshape(y_pred, [-1, y_true_shape[1]*y_true_shape[2], y_true_shape[3]])

        # [b, classes]
        # count how many of each class are present in 
        # each image, if there are zero, then assign
        # them a fixed weight of eps
        counts = tf.reduce_sum(y_true, axis=1)
        weights = 1. / (counts ** 2)
        weights = tf.where(tf.math.is_finite(weights), weights, self.epsilon)

        multed = tf.reduce_sum(y_true * y_pred, axis=1)
        summed = tf.reduce_sum(y_true + y_pred, axis=1)

        # [b]
        numerators = tf.reduce_sum(weights*multed, axis=-1)
        denom = tf.reduce_sum(weights*summed, axis=-1)
        dices = 1. - 2. * numerators / denom
        dices = tf.where(tf.math.is_finite(dices), dices, tf.zeros_like(dices))
        return tf.reduce_mean(dices)
    
class FocalTverskyLoss(tf.keras.losses.Loss):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.smooth=0.000001
        self.epsilon=K.epsilon()
        self.delta=0.7
        self.gamma=0.75

    def call(self, y_true, y_pred):
        y_pred = K.clip(y_pred, self.epsilon, 1. - self.epsilon) 

        tp = K.sum(y_true * y_pred, axis=[1,2,3])
        fn = K.sum(y_true * (1-y_pred), axis=[1,2,3])
        fp = K.sum((1-y_true) * y_pred, axis=[1,2,3])
        tversky_class = (tp + self.smooth)/(tp + self.delta*fn + (1-self.delta)*fp +  self.smooth)
        # Average class scores
        focal_tversky_loss = K.mean(K.pow((1-tversky_class), self.gamma))
        return focal_tversky_loss


class AsymUnifiedFocalLoss(tf.keras.losses.Loss):
    """The Unified Focal loss is a new compound loss function that unifies Dice-based and cross entropy-based loss functions into a single framework.
    Ref : https://github.com/mlyg/unified-focal-loss
    Paper: Unified Focal loss: Generalising Dice and cross entropy-based losses to handle class imbalanced medical image segmentation

    Deleted Background Class - enhancment etc. because we dont use
    Parameters
    ----------
    weight : float, optional
        represents lambda parameter and controls weight given to asymmetric Focal Tversky loss and asymmetric Focal loss, by default 0.5
    delta : float, optional
        controls weight given to each class, by default 0.6
    gamma : float, optional
        focal parameter controls the degree of background suppression and foreground enhancement, by default 0.5
    """
    def __init__(self, weight=0.5, delta=0.6, gamma=0.5,**kwargs):
        super().__init__(**kwargs)
        self.epsilon=K.epsilon()
        self.weight=weight
        self.delta=delta
        self.gamma=gamma

    def asymmetric_focal_tversky_loss(self,y_true, y_pred,delta=0.7, gamma=0.75):
        # Clip values to prevent division by zero error
        epsilon = self.epsilon
        y_pred = K.clip(y_pred, epsilon, 1. - epsilon)

        # Calculate true positives (tp), false negatives (fn) and false positives (fp)     
        tp = K.sum(y_true * y_pred, axis=[1,2])
        fn = K.sum(y_true * (1-y_pred), axis=[1,2])
        fp = K.sum((1-y_true) * y_pred, axis=[1,2])
        dice_class = (tp + epsilon)/(tp + delta*fn + (1-delta)*fp + epsilon)


        fore_dice = (1-dice_class) * K.pow(1-dice_class, -gamma) 

        # Average class scores
        loss = K.mean(tf.stack([fore_dice],axis=-1))

        return loss
    
    def asymmetric_focal_loss(self,y_true, y_pred,delta=0.7, gamma=2.):


        epsilon = self.epsilon
        y_pred = K.clip(y_pred, epsilon, 1. - epsilon)
        cross_entropy = -y_true * K.log(y_pred)

        fore_ce = delta * cross_entropy

        loss = K.mean(K.sum(tf.stack([fore_ce],axis=-1),axis=-1))

        return loss
    
    def call(self, y_true, y_pred):
        asymmetric_ftl = self.asymmetric_focal_tversky_loss(y_true,y_pred,delta=self.delta, gamma=self.gamma)
        asymmetric_fl = self.asymmetric_focal_loss(y_true,y_pred,delta=self.delta, gamma=self.gamma)
        if self.weight is not None:
            return (self.weight * asymmetric_ftl) + ((1-self.weight) * asymmetric_fl)  
        else:
            return asymmetric_ftl + asymmetric_fl